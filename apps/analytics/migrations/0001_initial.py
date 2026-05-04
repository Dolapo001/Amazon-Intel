import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("products", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TrendingProduct",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("discovery_date", models.DateField(default=django.utils.timezone.now)),
                ("bsr_change_pct", models.FloatField(help_text="BSR improvement % over detection window")),
                ("velocity_score", models.FloatField(help_text="Combined momentum score 0-100")),
                ("is_active", models.BooleanField(default=True, help_text="Currently trending")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("asin", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="trending_records", to="products.asin")),
            ],
            options={
                "ordering": ["-velocity_score"],
                "unique_together": {("asin", "discovery_date")},
            },
        ),
        migrations.CreateModel(
            name="CompetitorCluster",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("cluster_stats", models.JSONField(default=dict, help_text="Aggregated niche stats (avg price, total reviews)")),
                ("anchor_asin", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="competitor_cluster", to="products.asin")),
                ("competitors", models.ManyToManyField(related_name="competitor_of", to="products.asin")),
            ],
        ),
        migrations.CreateModel(
            name="OpportunityScore",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("niche_name", models.CharField(blank=True, max_length=256)),
                ("total_score", models.FloatField(help_text="Overall opportunity score 0-100")),
                ("profitability_index", models.FloatField(help_text="Based on avg monthly revenue")),
                ("competition_index", models.FloatField(help_text="High = Underserved (low reviews/ratings)")),
                ("demand_growth_pct", models.FloatField(help_text="Quarter-over-quarter growth", null=True)),
                ("recommendation", models.TextField(help_text="Human-readable insight")),
                ("computed_at", models.DateTimeField(auto_now=True)),
                ("category", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="opportunity_scores", to="products.category")),
            ],
            options={
                "ordering": ["-total_score"],
            },
        ),
    ]
