import datetime

from django.shortcuts import render
from django.utils import timezone
from django.views import View

from ..models import Product, Salida, SalidaNormalizada, Sucursal


class SalidaNormalizeView(View):
    template_name = "salida_normalizar.html"

    def get(self, request, *args, **kwargs):
        selected_date = self._selected_date(request)
        dates = self._dates()
        summary = self._summary(selected_date)
        errors = self._errors(selected_date)
        pending = self._pending(selected_date)
        return render(
            request,
            self.template_name,
            {
                "summary": summary,
                "errors": errors,
                "pending": pending,
                "selected_date": selected_date,
                "dates": dates,
                "ran": False,
            },
        )

    def post(self, request, *args, **kwargs):
        selected_date = self._selected_date(request)
        dates = self._dates()

        queryset = Salida.objects.filter(normalize_status__in=["pending", "error"])
        if selected_date:
            queryset = queryset.filter(fecha_salida=selected_date)

        created = 0
        updated = 0
        errors_count = 0

        for raw in queryset:
            issues = []

            sucursal_origen = None
            if raw.nombre_sucursal_origen:
                sucursal_origen = Sucursal.objects.filter(name__iexact=raw.nombre_sucursal_origen.strip()).first()
                if not sucursal_origen:
                    issues.append(f"Sucursal origen no encontrada: {raw.nombre_sucursal_origen}")
            else:
                issues.append("Sin sucursal origen")

            sucursal_destino = None
            if raw.nombre_sucursal_destino:
                sucursal_destino = Sucursal.objects.filter(name__iexact=raw.nombre_sucursal_destino.strip()).first()
                if not sucursal_destino:
                    issues.append(f"Sucursal destino no encontrada: {raw.nombre_sucursal_destino}")

            product = None
            if raw.sku:
                product = Product.objects.filter(code__iexact=raw.sku.strip()).first()
                if not product:
                    issues.append(f"Producto no encontrado: {raw.sku}")

            if issues:
                raw.normalize_status = "error"
                raw.normalize_notes = "; ".join(issues)
                raw.normalized_at = None
                raw.save(update_fields=["normalize_status", "normalize_notes", "normalized_at"])
                errors_count += 1
                continue

            payload = {
                "salida": raw.salida or "",
                "fecha_salida": raw.fecha_salida,
                "sku": raw.sku or "",
                "descripcion": raw.descripcion or "",
                "cantidad": raw.cantidad,
                "sucursal_origen": sucursal_origen,
                "sucursal_destino": sucursal_destino,
                "product": product,
                "origen_nombre": raw.nombre_sucursal_origen or "",
                "destino_nombre": raw.nombre_sucursal_destino or "",
                "entrada": raw.entrada or "",
                "fecha_entrada": raw.fecha_entrada,
                "comments": raw.comments or "",
            }

            existing = SalidaNormalizada.objects.filter(raw=raw).first()
            if existing:
                for field, value in payload.items():
                    setattr(existing, field, value)
                existing.save()
                updated += 1
            else:
                SalidaNormalizada.objects.create(raw=raw, **payload)
                created += 1

            raw.normalize_status = "ok"
            raw.normalize_notes = ""
            raw.normalized_at = timezone.now()
            raw.save(update_fields=["normalize_status", "normalize_notes", "normalized_at"])

        summary = self._summary(selected_date)
        errors = self._errors(selected_date)
        pending = self._pending(selected_date)

        return render(
            request,
            self.template_name,
            {
                "summary": summary,
                "errors": errors,
                "pending": pending,
                "selected_date": selected_date,
                "dates": dates,
                "ran": True,
                "run_result": {
                    "processed": queryset.count(),
                    "created": created,
                    "updated": updated,
                    "errors": errors_count,
                },
            },
        )

    def _dates(self):
        return list(
            Salida.objects.filter(fecha_salida__isnull=False)
            .order_by("-fecha_salida")
            .values_list("fecha_salida", flat=True)
            .distinct()
        )

    def _selected_date(self, request):
        raw_date = request.GET.get("fecha_salida") or request.POST.get("fecha_salida")
        if raw_date:
            try:
                return datetime.datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                return None
        dates = self._dates()
        return dates[0] if dates else None

    def _summary(self, selected_date):
        qs = Salida.objects.all()
        if selected_date:
            qs = qs.filter(fecha_salida=selected_date)
        return {
            "pending": qs.filter(normalize_status="pending").count(),
            "ok": qs.filter(normalize_status="ok").count(),
            "error": qs.filter(normalize_status="error").count(),
            "total": qs.count(),
        }

    def _errors(self, selected_date):
        qs = Salida.objects.filter(normalize_status="error")
        if selected_date:
            qs = qs.filter(fecha_salida=selected_date)
        return qs.order_by("-created_at")[:50]

    def _pending(self, selected_date):
        qs = Salida.objects.filter(normalize_status="pending")
        if selected_date:
            qs = qs.filter(fecha_salida=selected_date)
        return qs.order_by("-created_at")[:50]
