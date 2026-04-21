"""Catalog URL patterns — mounted under /v1/catalog/."""
from django.urls import path

from .catalog_views import CategoryItemsView, CategoryListView

urlpatterns = [
    path("categories/", CategoryListView.as_view(), name="catalog-categories"),
    path(
        "categories/<str:category_id>/items/",
        CategoryItemsView.as_view(),
        name="catalog-category-items",
    ),
]
