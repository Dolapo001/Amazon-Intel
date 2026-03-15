from rest_framework import serializers
from apps.products.serializers import ASINSerializer, CategorySerializer
from .models import TrendingProduct, CompetitorCluster, OpportunityScore

class TrendingProductSerializer(serializers.ModelSerializer):
    asin_details = ASINSerializer(source='asin', read_only=True)
    
    class Meta:
        model = TrendingProduct
        fields = ["asin", "discovery_date", "bsr_change_pct", "velocity_score", "is_active", "metadata", "asin_details"]

class CompetitorClusterSerializer(serializers.ModelSerializer):
    anchor_details = ASINSerializer(source='anchor_asin', read_only=True)
    competitors_details = ASINSerializer(source='competitors', many=True, read_only=True)
    
    class Meta:
        model = CompetitorCluster
        fields = ["anchor_asin", "updated_at", "cluster_stats", "anchor_details", "competitors_details"]

class OpportunityScoreSerializer(serializers.ModelSerializer):
    category_details = CategorySerializer(source='category', read_only=True)
    
    class Meta:
        model = OpportunityScore
        fields = ["category", "niche_name", "total_score", "profitability_index", "competition_index", "demand_growth_pct", "recommendation", "computed_at", "category_details"]
