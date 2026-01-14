import datetime

from django.shortcuts import render
from django.utils import timezone
from django.views import View

from ..models import Planificacion, PlanificacionNormalizada, PlanningEntry, Product, Sucursal


class PlanificacionNormalizeView(View):
    template_name = "planificacion_normalizar.html"

    def get(self, request, *args, **kwargs):
        self._sync_from_legacy()
        selected_month = self._selected_month(request)
        months = self._months()
        summary = self._summary(selected_month)
        errors = (
            Planificacion.objects.filter(normalize_status="error")
            .filter(plan_month=selected_month)
            .order_by("-created_at")[:50]
            if selected_month
            else []
        )
        pending = (
            Planificacion.objects.filter(normalize_status="pending")
            .filter(plan_month=selected_month)
            .order_by("-created_at")[:50]
            if selected_month
            else []
        )
        return render(
            request,
            self.template_name,
            {
                "summary": summary,
                "errors": errors,
                "pending": pending,
                "ran": False,
                "months": months,
                "selected_month": selected_month,
            },
        )

    def post(self, request, *args, **kwargs):
        self._sync_from_legacy()
        selected_month = self._selected_month(request)
        months = self._months()

        to_process = Planificacion.objects.filter(normalize_status__in=["pending", "error"])
        if selected_month:
            to_process = to_process.filter(plan_month=selected_month)
        created = 0
        updated = 0
        errors_count = 0

        for raw in to_process:
            issues = []

            sucursal = None
            if raw.sucursal:
                sucursal = Sucursal.objects.filter(name__iexact=raw.sucursal.strip()).first()
                if not sucursal:
                    issues.append(f"Sucursal no encontrada: {raw.sucursal}")
            else:
                issues.append("Sin sucursal")

            product = None
            if raw.item_code:
                product = Product.objects.filter(code__iexact=raw.item_code.strip()).first()
                if not product:
                    issues.append(f"Producto no encontrado: {raw.item_code}")

            if issues:
                raw.normalize_status = "error"
                raw.normalize_notes = "; ".join(issues)
                raw.normalized_at = None
                raw.save(update_fields=["normalize_status", "normalize_notes", "normalized_at"])
                errors_count += 1
                continue

            # Evita choque con la restriccion unica (plan_month, item_code, sucursal)
            existing = PlanificacionNormalizada.objects.filter(
                plan_month=raw.plan_month,
                item_code=raw.item_code,
                sucursal=sucursal,
            ).first()
            if existing:
                existing.raw = raw
                existing.tipo_carga = raw.tipo_carga
                existing.item_name = raw.item_name
                existing.product = product
                existing.origen_picking = raw.origen_picking
                existing.a_despachar_total = raw.a_despachar_total
                existing.save()
                updated += 1
            else:
                PlanificacionNormalizada.objects.create(
                    raw=raw,
                    plan_month=raw.plan_month,
                    tipo_carga=raw.tipo_carga,
                    item_code=raw.item_code,
                    item_name=raw.item_name,
                    sucursal=sucursal,
                    product=product,
                    origen_picking=raw.origen_picking,
                    a_despachar_total=raw.a_despachar_total,
                )
                created += 1

            raw.normalize_status = "ok"
            raw.normalize_notes = ""
            raw.normalized_at = timezone.now()
            raw.save(update_fields=["normalize_status", "normalize_notes", "normalized_at"])

        summary = self._summary(selected_month)
        errors = (
            Planificacion.objects.filter(normalize_status="error")
            .filter(plan_month=selected_month)
            .order_by("-created_at")[:50]
            if selected_month
            else []
        )
        pending = (
            Planificacion.objects.filter(normalize_status="pending")
            .filter(plan_month=selected_month)
            .order_by("-created_at")[:50]
            if selected_month
            else []
        )

        run_result = {
            "processed": to_process.count(),
            "created": created,
            "updated": updated,
            "errors": errors_count,
        }

        return render(
            request,
            self.template_name,
            {
                "summary": summary,
                "errors": errors,
                "pending": pending,
                "ran": True,
                "run_result": run_result,
                "months": months,
                "selected_month": selected_month,
            },
        )

    @staticmethod
    def _summary(selected_month):
        base = Planificacion.objects.all()
        if selected_month:
            base = base.filter(plan_month=selected_month)
        return {
            "pending": base.filter(normalize_status="pending").count(),
            "ok": base.filter(normalize_status="ok").count(),
            "error": base.filter(normalize_status="error").count(),
            "total": base.count(),
        }

    @staticmethod
    def _months():
        return list(Planificacion.objects.dates("plan_month", "day", order="DESC"))

    def _selected_month(self, request):
        month_raw = request.POST.get("plan_month") or request.GET.get("plan_month")
        if month_raw:
            try:
                return datetime.date.fromisoformat(month_raw)
            except ValueError:
                return None
        months = self._months()
        return months[0] if months else None

    @staticmethod
    def _sync_from_legacy():
        # Sincroniza registros de PlanningEntry (legacy) hacia la tabla cruda Planificacion si no existen.
        legacy = (
            PlanningEntry.objects.select_related("batch")
            .values("batch__plan_date", "item_code", "item_name", "sucursal", "tipo_carga", "origen_picking", "a_despachar_total")
        )
        to_create = []
        for row in legacy:
            plan_date = row.get("batch__plan_date")
            if not plan_date:
                continue
            exists = Planificacion.objects.filter(
                plan_month=plan_date,
                item_code=row.get("item_code") or "",
                sucursal=row.get("sucursal") or "",
            ).exists()
            if exists:
                continue
            to_create.append(
                Planificacion(
                    plan_month=plan_date,
                    tipo_carga=row.get("tipo_carga") or "",
                    item_code=row.get("item_code") or "",
                    item_name=row.get("item_name") or "",
                    sucursal=row.get("sucursal") or "",
                    origen_picking=row.get("origen_picking") or "",
                    a_despachar_total=row.get("a_despachar_total"),
                    normalize_status="pending",
                )
            )
        if to_create:
            Planificacion.objects.bulk_create(to_create, ignore_conflicts=True)
