from django.db import models

from .planificacion import Planificacion
from .product import Product
from .sucursal import Sucursal


class PlanificacionNormalizada(models.Model):
    raw = models.OneToOneField(Planificacion, on_delete=models.CASCADE, related_name="normalizada")
    plan_month = models.DateField()
    tipo_carga = models.CharField(max_length=100, blank=True, default="")
    item_code = models.CharField(max_length=100, blank=True, default="")
    item_name = models.CharField(max_length=255, blank=True, default="")
    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True)
    origen_picking = models.CharField(max_length=255, blank=True, default="")
    a_despachar_total = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Planificacion normalizada"
        verbose_name_plural = "Planificaciones normalizadas"
        ordering = ["-plan_month", "item_code", "sucursal__name"]
        unique_together = ["plan_month", "item_code", "sucursal"]

    def __str__(self) -> str:
        return f"{self.plan_month} - {self.item_code} - {self.sucursal.name}"
