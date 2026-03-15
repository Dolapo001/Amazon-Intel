"""Initial migration — creates Category, ASIN, RevenueEstimate, ReviewAnalysis, BSRSnapshot."""
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("amazon_id", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=256)),
                ("bsr_revenue_multiplier", models.FloatField(default=1.0)),
                ("seasonality_indices", models.JSONField(default=list)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name_plural": "categories"},
        ),
        migrations.CreateModel(
            name="ASIN",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("asin", models.CharField(db_index=True, max_length=10, unique=True)),
                ("title", models.CharField(blank=True, max_length=512)),
                ("brand", models.CharField(blank=True, max_length=256)),
                ("image_url", models.URLField(blank=True)),
                ("tier", models.SmallIntegerField(choices=[(1, "Tier 1"), (2, "Tier 2"), (3, "Tier 3")], default=3)),
                ("query_count", models.PositiveIntegerField(default=0)),
                ("current_bsr", models.IntegerField(blank=True, null=True)),
                ("current_price", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("current_rating", models.FloatField(blank=True, null=True)),
                ("current_review_count", models.IntegerField(blank=True, null=True)),
                ("last_ingested_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("category", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="products.category")),
            ],
            options={"indexes": [models.Index(fields=["tier", "last_ingested_at"], name="products_as_tier_bc3d9d_idx")]},
        ),
        migrations.CreateModel(
            name="RevenueEstimate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("monthly_revenue", models.DecimalField(decimal_places=2, max_digits=12)),
                ("yoy_change_pct", models.FloatField(blank=True, null=True)),
                ("confidence", models.FloatField()),
                ("seasonality_adjusted", models.BooleanField(default=False)),
                ("model_features", models.JSONField(default=dict)),
                ("computed_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("asin", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="revenue_estimate", to="products.asin")),
            ],
        ),
        migrations.CreateModel(
            name="ReviewAnalysis",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("sentiment_score", models.FloatField()),
                ("positive_themes", models.JSONField(default=list)),
                ("negative_themes", models.JSONField(default=list)),
                ("review_velocity", models.FloatField(blank=True, null=True)),
                ("total_reviews_analysed", models.IntegerField(default=0)),
                ("computed_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("asin", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="review_analysis", to="products.asin")),
            ],
        ),
        migrations.CreateModel(
            name="BSRSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("date", models.DateField(db_index=True)),
                ("bsr_rank", models.IntegerField()),
                ("price", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("asin", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bsr_snapshots", to="products.asin")),
                ("category", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="products.category")),
            ],
            options={
                "indexes": [models.Index(fields=["asin", "date"], name="products_bs_asin_id_5b1c64_idx")],
                "unique_together": {("asin", "date")},
            },
        ),
    ]
