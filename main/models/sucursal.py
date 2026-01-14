from django.db import models


class Sucursal(models.Model):
    bpl_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sucursal"
        verbose_name_plural = "Sucursales"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.bpl_id})"
