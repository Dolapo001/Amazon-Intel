import os
import sys
import django
from datetime import date, timedelta
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
django.setup()

from apps.products.models import ASIN, BSRSnapshot

def seed_asin_history(asin_code):
    try:
        asin_obj = ASIN.objects.get(asin=asin_code)
    except ASIN.DoesNotExist:
        print(f"ASIN {asin_code} not found.")
        return

    print(f"🌱 Seeding history for {asin_code}...")
    today = date.today()
    
    # 1. Today's snapshot (baseline)
    BSRSnapshot.objects.update_or_create(
        asin=asin_obj, date=today,
        defaults={"bsr_rank": asin_obj.current_bsr or 500}
    )
    
    # 2. Year ago snapshot
    # Let's say it was 20% worse a year ago (higher BSR)
    year_ago = today - timedelta(days=365)
    baseline_bsr = int((asin_obj.current_bsr or 500) * 1.25)
    BSRSnapshot.objects.update_or_create(
        asin=asin_obj, date=year_ago,
        defaults={"bsr_rank": baseline_bsr}
    )
    print(f"  ✅ Seeded baseline for {year_ago}: BSR {baseline_bsr}")

    # 3. Last 30 days trend
    for i in range(1, 31):
        d = today - timedelta(days=i)
        # linear interpolation-ish
        rank = int(baseline_bsr - (baseline_bsr - (asin_obj.current_bsr or 500)) * (365-i)/365)
        BSRSnapshot.objects.update_or_create(
            asin=asin_obj, date=d,
            defaults={"bsr_rank": rank}
        )
    print(f"  ✅ Seeded 30-day progression")

    # 4. Clear/Update revenue estimate to reflect new history
    from apps.products.models import RevenueEstimate
    RevenueEstimate.objects.filter(asin=asin_obj).delete()
    print(f"  ✅ Cleared cached revenue estimate (will recompute on next API call)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python seed_history.py <ASIN>")
    else:
        seed_asin_history(sys.argv[1])
