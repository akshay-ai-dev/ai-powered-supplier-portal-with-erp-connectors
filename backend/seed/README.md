# Seed data

Demo data only: no real suppliers, customers or personal data (SRS §8).

Per mock ERP (SRS §5.3): 4 suppliers (1 blocked), 8 machinery parts (5 parts and 3 components with BOMs), and 6 open requisitions.

- `drawings/`: sample request drawings and specs (PDF, images)
- `packing_lists/`: sample packing lists and delivery notes for the AI pre-fill (SRS §6.2)
- `seed.db`: clean seed database. Reset copies it over `data/portal.db` (`SEED_DB_PATH`).
