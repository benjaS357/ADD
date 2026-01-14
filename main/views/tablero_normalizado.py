import datetime
from decimal import Decimal

from django.shortcuts import render
from django.views import View
from django.http import HttpResponse
import csv

from ..models import PlanificacionNormalizada, SalidaNormalizada


class TableroNormalizadoView(View):
    template_name = "tablero_normalizado.html"

    def get(self, request, *args, **kwargs):
        start_date = self._selected_date(request)
        selected_origin = self._selected_origin(request)
        single_day = self._single_day(request)
        mode_all = request.GET.get("mode") == "all"
        dates = [start_date] if (start_date and single_day) else ([start_date + datetime.timedelta(days=i) for i in range(8)] if start_date else [])

        plan_data = self._plan_by_date_dest_group(dates)
        salida_data = self._salidas_by_origin_dest_group_date(dates, selected_origin)
        if mode_all:
            salida_data = self._aggregate_salidas(salida_data)
        origenes = sorted(salida_data.keys(), key=lambda k: (k[1] or ""))
        origin_choices = self._origin_choices()

        table = self._build_table(dates, plan_data, salida_data, origenes)

        # Export CSV with same filters
        if request.GET.get("export") == "csv":
            return self._export_csv(dates, table)

        return render(
            request,
            self.template_name,
            {
                "dates": dates,
                "start_date": start_date,
                "selected_origin": selected_origin,
                "single_day": single_day,
                "mode_all": mode_all,
                "origin_choices": origin_choices,
                "origenes": origenes,
                "table": table,
            },
        )

    def post(self, request, *args, **kwargs):
        return self.get(request, *args, **kwargs)

    def _selected_date(self, request):
        raw_date = request.GET.get("start_date") or request.POST.get("start_date")
        if raw_date:
            try:
                return datetime.datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                return self._default_date()
        return self._default_date()

    def _selected_origin(self, request):
        raw = request.GET.get("origin") or request.POST.get("origin")
        try:
            return int(raw) if raw else None
        except (TypeError, ValueError):
            return None

    def _single_day(self, request):
        return (request.GET.get("single_day") or request.POST.get("single_day")) == "1"

    def _default_date(self):
        latest_salida = SalidaNormalizada.objects.order_by("-fecha_salida").values_list("fecha_salida", flat=True).first()
        latest_plan = PlanificacionNormalizada.objects.order_by("-plan_month").values_list("plan_month", flat=True).first()
        candidates = [d for d in [latest_salida, latest_plan] if d]
        return max(candidates) if candidates else None

    def _plan_by_date_dest_group(self, dates):
        """Return plan grouped by fecha -> destino -> grupo.

        Falls back to Planificacion cruda si no hay normalizada para esa fecha.
        """
        by_date = {}
        if not dates:
            return by_date

        # Normalizada primero
        qs_norm = PlanificacionNormalizada.objects.filter(plan_month__in=dates).select_related("product", "sucursal")
        for row in qs_norm:
            date_key = row.plan_month
            dest = row.sucursal
            group = (row.product.group if row.product and row.product.group else "SIN GRUPO").strip() or "SIN GRUPO"
            qty = Decimal(row.a_despachar_total or 0)
            dest_bucket = by_date.setdefault(date_key, {}).setdefault(dest.id, {"name": dest.name, "groups": {}})
            dest_bucket["groups"].setdefault(group, Decimal("0"))
            dest_bucket["groups"][group] += qty

        # Si no hay normalizada en alguna fecha, usar Planificacion cruda como respaldo
        missing_dates = [d for d in dates if d not in by_date]
        if missing_dates:
            from ..models import Planificacion, Product, Sucursal

            raw_qs = Planificacion.objects.filter(plan_month__in=missing_dates)
            for row in raw_qs:
                date_key = row.plan_month
                dest = None
                if row.sucursal:
                    dest = Sucursal.objects.filter(name__iexact=row.sucursal.strip()).first()
                if not dest:
                    continue
                product = None
                if row.item_code:
                    product = Product.objects.filter(code__iexact=row.item_code.strip()).first()
                group = (product.group if product and product.group else "SIN GRUPO").strip() or "SIN GRUPO"
                qty = Decimal(row.a_despachar_total or 0)
                dest_bucket = by_date.setdefault(date_key, {}).setdefault(dest.id, {"name": dest.name, "groups": {}})
                dest_bucket["groups"].setdefault(group, Decimal("0"))
                dest_bucket["groups"][group] += qty

        return by_date

    def _salidas_by_origin_dest_group_date(self, dates, selected_origin_id=None):
        by_origin = {}
        if not dates:
            return by_origin
        qs = (
            SalidaNormalizada.objects.filter(fecha_salida__in=dates)
            .select_related("product", "sucursal_origen", "sucursal_destino")
        )
        if selected_origin_id:
            qs = qs.filter(sucursal_origen_id=selected_origin_id)
        for row in qs:
            if not row.sucursal_destino:
                continue
            origin = row.sucursal_origen
            dest = row.sucursal_destino
            group = (row.product.group if row.product and row.product.group else "SIN GRUPO").strip() or "SIN GRUPO"
            qty = Decimal(row.cantidad or 0)
            key_origin = (origin.id, origin.name if origin else "")
            origin_bucket = by_origin.setdefault(key_origin, {})
            dest_bucket = origin_bucket.setdefault(dest.id, {"name": dest.name, "groups": {}})
            group_bucket = dest_bucket["groups"].setdefault(group, {})
            group_bucket.setdefault(row.fecha_salida, Decimal("0"))
            group_bucket[row.fecha_salida] += qty
        return by_origin

    def _origin_choices(self):
        qs = SalidaNormalizada.objects.values_list("sucursal_origen_id", "sucursal_origen__name").distinct()
        return sorted([(oid, name) for oid, name in qs if oid and name], key=lambda t: t[1])

    def _aggregate_salidas(self, salida_data):
        """Combine all origins into a single bucket 'Todos'."""
        combined = {}
        for (_oid, _oname), dests in salida_data.items():
            for dest_id, dest_info in dests.items():
                dest_bucket = combined.setdefault(dest_id, {"name": dest_info["name"], "groups": {}})
                for group, by_date in dest_info["groups"].items():
                    gb = dest_bucket["groups"].setdefault(group, {})
                    for d, qty in by_date.items():
                        gb[d] = gb.get(d, Decimal("0")) + qty
        return {(-1, "Todos"): combined} if combined else {}

    def _export_csv(self, dates, table):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=tablero_normalizado.csv"
        writer = csv.writer(response)
        header = ["Cendis", "Sucursal destino", "Categoria"] + [d.strftime("%Y-%m-%d") for d in dates]
        writer.writerow(header)
        for origen in table:
            origin_name = origen["origin_name"]
            for destino in origen["destinos"]:
                dest_name = destino["name"]
                for group, cells in destino["groups"].items():
                    row = [origin_name, dest_name, group]
                    for cell in cells:
                        row.append(f"{cell['percent']}%" if cell["percent"] is not None else "0%")
                    writer.writerow(row)
        return response

    def _build_table(self, dates, plan_data, salida_data, origenes):
        table = []
        for origin_id, origin_name in origenes:
            dests = salida_data.get((origin_id, origin_name), {})
            origin_block = {"origin_name": origin_name, "destinos": []}
            for dest_id, dest_info in sorted(dests.items(), key=lambda item: item[1]["name"]):
                row_groups = {}
                all_groups = set(dest_info["groups"].keys())
                for d in dates:
                    if d in plan_data and dest_id in plan_data[d]:
                        all_groups.update(plan_data[d][dest_id]["groups"].keys())
                for group in sorted(all_groups):
                    cells = []
                    for d in dates:
                        plan_qty = Decimal("0")
                        if d in plan_data and dest_id in plan_data[d]:
                            plan_qty = plan_data[d][dest_id]["groups"].get(group, Decimal("0"))
                        sent_qty = dest_info["groups"].get(group, {}).get(d, Decimal("0"))
                        percent = Decimal("0")
                        if plan_qty > 0:
                            percent = (sent_qty / plan_qty) * Decimal("100")
                        cells.append({"date": d, "percent": percent.quantize(Decimal("1.")) if plan_qty > 0 else None, "plan": plan_qty, "sent": sent_qty})
                    row_groups[group] = cells
                origin_block["destinos"].append({"name": dest_info["name"], "groups": row_groups})
            table.append(origin_block)
        return table
