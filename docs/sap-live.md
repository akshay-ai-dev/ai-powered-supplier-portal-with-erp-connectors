# ERP Monitor: SAP live (read-only)

The **SAP live** tab in the ERP Monitor reads records straight from an SAP S/4HANA system.
It only reads. Nothing is ever created, changed or deleted in SAP, and nothing is stored in
the portal's database.

Who can see it: **buyers and admins** only. Suppliers and inspectors do not see the ERP Monitor
at all (menu hidden, page and API blocked).

The other two tabs, **SAP (demo)** and **Infor LN (demo)**, show the portal's own mock ERP data
from our database. They are not real ERP systems.

---

## 1. How it works

```
Buyer / admin ──(portal login)──> Portal backend ──(1 read-only SAP user / key)──> SAP S/4HANA
                                       │
                                       └── checks the role first (buyer or admin, else blocked)
```

1. The buyer opens **ERP Monitor → SAP live** and picks a tab.
2. The backend checks the user is a buyer or admin.
3. The backend calls SAP's standard OData API with **one** technical login kept in `.env`.
4. SAP returns the first 20 records; the portal shows them as they are. Nothing is saved.

Buyers never type a SAP password. They only use their normal portal login.

| Tab | SAP API (OData service / entity) | Search by |
|---|---|---|
| Purchase orders | `API_PURCHASEORDER_PROCESS_SRV / A_PurchaseOrder` | PO number |
| Suppliers | `API_BUSINESS_PARTNER / A_Supplier` | Supplier No |
| Requisitions | `API_PURCHASEREQ_PROCESS_SRV / A_PurchaseRequisitionItem` | Requisition number |
| Goods receipts | `API_MATERIAL_DOCUMENT_SRV / A_MaterialDocumentHeader` | Material document number |
| Supplier invoices | `API_SUPPLIERINVOICE_PROCESS_SRV / A_SupplierInvoice` | Invoice number |
| Materials | `API_PRODUCT_SRV / A_Product` | Product ID |

Code: `backend/app/connectors/sap_live.py` (the SAP calls),
`backend/app/routers/erp_monitor.py` (`GET /api/erp-monitor/live/sap/{view}?q=`),
`frontend/src/app/(app)/erp-monitor/page.tsx` (the tab).

Only a fixed list of views exists, and search accepts letters, digits, `-` and `_` only, so the
browser can never send its own query to SAP.

---

## 2. Today: SAP sandbox (demo data)

SAP's Business Accelerator Hub sandbox holds SAP's own demo company. Its suppliers and POs are
not ours (our demo suppliers such as ABC do not exist there).

`.env`:

```env
SAP_MODE=sandbox
SAP_API_HUB_URL=https://sandbox.api.sap.com
SAP_API_HUB_KEY=<your key from api.sap.com → Show API Key>
```

Then `docker compose up --build -d backend`.

---

## 3. Going real: a company's own SAP system

No code change is needed. Only `.env` changes.

**Step 1. The SAP system owner creates a read-only technical user.**
Whoever owns the SAP system does this: the client company's SAP Basis / security team, or our
own SAP team if it is our system. The user (for example `PORTAL_READ`) needs:

- display-only authorization for the 6 OData services in the table above, and nothing else;
- the services activated / exposed (on-premise: in the SAP Gateway; S/4HANA Cloud: through a
  communication arrangement);
- ideally, a limit to the right company code(s) or plant(s), so the portal only sees what it
  should.

**Step 2. Put the details in `.env`** (never commit `.env`):

```env
SAP_MODE=real
SAP_BASE_URL=https://<company-sap-host>       # host only; /sap/opu/odata/sap is added automatically
SAP_CLIENT=100                                # the SAP client (mandant); ask the SAP team
SAP_USERNAME=PORTAL_READ
SAP_PASSWORD=<password>
```

**Step 3.** `docker compose up --build -d backend`, then open ERP Monitor → SAP live.

To switch the tab off, leave `SAP_MODE` empty.

---

## 4. What does a buyer see? All data or only his own?

**Today: all of it.** Every buyer and admin sees the same SAP records, namely everything the one
technical SAP user is allowed to see. SAP does not know which portal buyer is asking, and the
portal does not know which SAP supplier number belongs to which portal supplier.

This is different from the portal's own pages (Requirements, Suppliers, Purchase Orders), which
are already narrowed to each buyer's own suppliers.

| Page | What a buyer sees |
|---|---|
| Portal's own pages | Only his own requirements, suppliers and POs |
| ERP Monitor → SAP live | Everything the SAP technical user can see (same for all buyers) |

For the POC and demo this is fine (it is SAP's demo data, read-only).

### Option A: limit everyone (no code change)

Ask the SAP team to restrict the technical user to certain company codes / plants. This narrows
what **all** buyers see together, not each buyer separately.

### Option B: each buyer sees only his own suppliers (recommended next step, needs code)

1. Add a column to the portal's suppliers, e.g. `sap_supplier_no`, linking each portal supplier
   to its SAP supplier number:

   | Portal supplier | SAP Supplier No |
   |---|---|
   | ABC Pvt Ltd | 1000030 |
   | XYZ Industries | 17300001 |

2. Let a buyer or admin fill it in (supplier page), or import it once from SAP.
3. In SAP live, look up the logged-in buyer's suppliers and add a filter to every SAP call,
   e.g. `Supplier eq '1000030' or Supplier eq '17300001'` for POs, `InvoicingParty eq ...` for
   invoices. Admins keep seeing everything.

The link is stored only in our database; nothing is written to SAP. With the sandbox you would
link our demo suppliers to sandbox numbers, and the rows shown would carry SAP's own names
(e.g. "vender for WHT 1"), because the data comes from SAP.

### Option C: each buyer logs in to SAP with his own SAP account

Single sign-on / principal propagation: SAP itself filters by the buyer's own SAP permissions.
Most accurate, but needs every buyer to have a SAP account and a much bigger setup. Not needed
for the POC.

---

## 5. Troubleshooting

| Message on screen | Meaning / fix |
|---|---|
| Live SAP is switched off… | `SAP_MODE` is empty. Set it in `.env` and rebuild the backend. |
| SAP_API_HUB_KEY is missing… | Sandbox mode without a key. |
| SAP_MODE=real needs SAP_BASE_URL… | Real mode with a missing address, user or password. |
| SAP rejected the credentials (401) | Wrong key, user or password. |
| SAP rate limit reached (429) | Sandbox limit; wait a minute. |
| SAP returned HTTP 403 / 404 | The user lacks authorization, or the service is not activated. |
| Could not reach SAP… | Network / VPN / firewall, or SAP answered with something unexpected. Check `docker compose logs backend`. |

Note: the sandbox sends gzip-compressed answers; the connector unzips them automatically.
