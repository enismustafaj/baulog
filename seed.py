"""Seed script — populates the owner database with known property owners.

Run this once after setup or whenever the database is recreated:

    uv run python seed.py
"""

from owner_repository import OwnerRepository


def seed_owners(repo: OwnerRepository) -> None:
    existing = {o["name"] for o in repo.list_all()}

    owners = [
        dict(
            name="Huber & Partner Immobilienverwaltung GmbH",
            property_name="WEG Immanuelkirchstraße 26",
            street="Friedrichstrasse 112",
            postal_code="10117",
            city="Berlin",
            email="info@huber-partner-verwaltung.de",
            phone="+49 30 12345-0",
            iban="DE89 3704 0044 0532 0130 00",
            bic="COBADEFFXXX",
            bank="Commerzbank Berlin",
            tax_number="13/456/78901",
        ),
    ]

    added = 0
    for owner in owners:
        if owner["name"] not in existing:
            repo.add(**owner)
            print(f"  + {owner['name']} -> {owner['property_name']}")
            added += 1
        else:
            print(f"  ~ {owner['name']} (already exists, skipped)")

    print(f"\n{added} owner(s) added, {len(owners) - added} skipped.")


if __name__ == "__main__":
    repo = OwnerRepository()
    print("Seeding owners...")
    seed_owners(repo)
