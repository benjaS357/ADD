from django.db import models


class Sendis(models.Model):
    origin = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name = "Cendis"
        verbose_name_plural = "Cendis"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.origin}"
