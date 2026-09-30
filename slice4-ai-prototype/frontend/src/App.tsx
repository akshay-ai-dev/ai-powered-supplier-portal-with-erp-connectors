import { useEffect, useRef, useState } from 'react';
import {
  api, errorMessage, jsonPost,
  type AwardDraft, type ChatReply, type Comparison, type ErpCall,
  type PrefillResult, type RankedOffer, type RequestSummary,
} from './api';

type Message = { role: 'user' | 'bot'; text: string };
type DemoConfirmation = {
  requestId: string;
  supplierName: string;
  supplierId: string;
  reason: string | null;
};

const ERP_NAMES: Record<string, string> = { SAP: 'SAP', LN: 'Infor LN' };
const OPERATION_NAMES: Record<string, string> = { createPurchaseOrder: 'Create purchase order' };

function ErpCallSummary({ call, supplierName }: { call: ErpCall; supplierName?: string }) {
  const { payload } = call;
  const rows: [string, string][] = [
    ['ERP system', ERP_NAMES[call.erp] ?? call.erp],
    ['Action', OPERATION_NAMES[call.operation] ?? call.operation],
    ['Requisition', payload.requisition],
    ['Supplier', supplierName ? `${supplierName} (${payload.supplier})` : payload.supplier],
    ['Quantity', String(payload.quantity)],
    ['Unit price', `${payload.currency} ${money(payload.unitPrice, payload.currency)}`],
    ['Total', `${payload.currency} ${money(payload.unitPrice * payload.quantity, payload.currency)}`],
    ['Delivery date', payload.deliveryDate],
    ['Draft reference', call.idempotencyKey],
  ];
  return <div className="tablewrap"><table><tbody>
    {rows.map(([label, value]) => <tr key={label}><th>{label}</th><td>{value}</td></tr>)}
  </tbody></table></div>;
}
// INR uses Indian digit grouping (2,25,600.00); other currencies use 225,600.00.
const money = (value: number, currency?: string | null) =>
  value.toLocaleString(currency === 'INR' ? 'en-IN' : 'en-US', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });

export default function App() {
  const [mode, setMode] = useState('Loading…');
  const [requests, setRequests] = useState<RequestSummary[]>([]);
  const [loadError, setLoadError] = useState('');
  const [selected, setSelected] = useState<RequestSummary | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [compareError, setCompareError] = useState('');
  const [supplierId, setSupplierId] = useState('');
  const [reason, setReason] = useState('');
  const [award, setAward] = useState<AwardDraft | null>(null);
  const [awardError, setAwardError] = useState('');
  // Demo confirmation lives in page state only: no ERP call, no PO number, no data change.
  const [confirmation, setConfirmation] = useState<DemoConfirmation | null>(null);
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [history, setHistory] = useState<Record<string, unknown>[]>([]);
  const [asking, setAsking] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [poQty, setPoQty] = useState('');
  const [prefill, setPrefill] = useState<PrefillResult | null>(null);
  const [prefillError, setPrefillError] = useState('');
  const [extracting, setExtracting] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    async function load() {
      try {
        const [status, list] = await Promise.all([
          api<{ liveAIReady: boolean }>('/api/status'),
          api<{ requests: RequestSummary[] }>('/api/requests'),
        ]);
        setMode(status.liveAIReady
          ? 'OpenAI configured · sample data'
          : 'Sample data · add OpenAI key for AI');
        setRequests(list.requests);
      } catch (error) { setLoadError(errorMessage(error)); }
    }
    void load();
  }, []);

  useEffect(() => { feedRef.current?.scrollTo(0, feedRef.current.scrollHeight); }, [messages]);

  async function selectRequest(request: RequestSummary) {
    setSelected(request);
    setComparison(null);
    setCompareError('');
    clearAward();
    setAwardError('');
    setReason('');
    setSupplierId('');
    try {
      const result = await api<Comparison>(
        `/api/requests/${encodeURIComponent(request.id)}/comparison`,
      );
      setComparison(result);
      // No default pick when offers are unranked (mixed currencies): the buyer must choose.
      const ranked = result.rankingStatus !== 'currency_review_required';
      setSupplierId(result.awardable && ranked ? result.ranking?.[0]?.supplierId ?? '' : '');
    } catch (error) { setCompareError(errorMessage(error)); }
  }

  function clearAward() {
    setAward(null);
    setConfirmation(null);
  }

  // Why the current draft cannot be confirmed, or null when it can.
  function confirmBlocker(): string | null {
    if (!selected || !award?.draft || award.status !== 'awaiting_buyer_confirmation') {
      return 'Prepare a valid award draft first.';
    }
    if (award.requestId !== selected.id) return 'This draft belongs to a different request.';
    if (!comparison?.awardable) {
      return comparison?.awardBlockedReason ?? `${selected.id} cannot be awarded.`;
    }
    if (award.justificationRequired
      && (award.justificationMissing || !award.justificationProvided?.trim())) {
      return award.justificationProvided?.trim()
        ? `${award.justificationProblem ?? 'The reason is not specific enough.'} Update the `
          + 'reason above, then prepare the award draft again before confirming.'
        : 'This supplier is outside the recommendation. Enter a reason above, then '
          + 'prepare the award draft again before confirming.';
    }
    return null;
  }

  function confirmAward() {
    // Re-check at click time; never trust a button state alone.
    if (confirmBlocker() || !award?.awardTo || !selected) return;
    setConfirmation({
      requestId: selected.id,
      supplierName: award.awardTo.supplierName,
      supplierId: award.awardTo.supplierId,
      reason: award.justificationProvided?.trim() || null,
    });
  }

  async function prepareAward() {
    if (!selected || !supplierId || !comparison?.awardable) return;
    clearAward();
    setAwardError('');
    try {
      const result = await api<AwardDraft>('/api/draft-award', jsonPost({
        request_id: selected.id,
        supplier_id: supplierId,
        justification: reason,
      }));
      setAward(result);
    } catch (error) { setAwardError(errorMessage(error)); }
  }

  async function ask() {
    const prompt = question.trim();
    if (!prompt || asking) return;
    setQuestion('');
    setMessages(previous => [...previous, { role: 'user', text: prompt }]);
    setAsking(true);
    try {
      const reply = await api<ChatReply>('/api/chat', jsonPost({ prompt, history }));
      setHistory(reply.messages);
      setMessages(previous => [
        ...previous,
        { role: 'bot', text: reply.answer },
        ...(reply.drafts ?? []).map(draft => ({
          role: 'bot' as const,
          text: `Draft for review: ${JSON.stringify(draft.result, null, 2)}`,
        })),
      ]);
    } catch (error) {
      setMessages(previous => [...previous, {
        role: 'bot', text: `Error: ${errorMessage(error)}`,
      }]);
    } finally { setAsking(false); }
  }

  async function extract() {
    if (!file) { setPrefillError('Choose a file first.'); return; }
    setPrefill(null);
    setPrefillError('');
    setExtracting(true);
    const form = new FormData();
    form.append('file', file);
    if (poQty !== '') form.append('po_quantity', poQty);
    try {
      setPrefill(await api<PrefillResult>('/api/prefill', { method: 'POST', body: form }));
    } catch (error) { setPrefillError(errorMessage(error)); }
    finally { setExtracting(false); }
  }

  const offers: RankedOffer[] = comparison?.ranking ?? [];
  const awardable = comparison?.awardable === true;
  const blocker = award?.draft ? confirmBlocker() : null;
  // Closed/cancelled/awarded requests are history; others are simply not locked yet.
  const historical = /^(closed|cancelled|awarded)/i.test(comparison?.status ?? '');
  const currencyReview = comparison?.rankingStatus === 'currency_review_required';
  // Exchange rate returned by the backend when offers in different currencies were compared.
  const fx = currencyReview ? null : comparison?.exchangeRate ?? null;
  const fxRateText = fx ? Object.entries(fx.ratesToBase)
    .filter(([currency]) => currency !== fx.baseCurrency)
    .map(([currency, rate]) => `1 ${currency} = ${rate} ${fx.baseCurrency}`)
    .join(' · ') : '';
  const fieldLabels: Record<string, string> = {
    shipDate: 'Ship date', carrier: 'Carrier', trackingNumber: 'Tracking number',
    quantity: 'Quantity', lotNumbers: 'Lot / serial numbers',
  };
  const showValue = (value: unknown) =>
    Array.isArray(value) ? value.join(', ') : String(value);
  // Fall back to the older response fields if the backend does not send the newer ones.
  const manualEntry = prefill?.manualEntryRequired ?? (prefill?.unreadableFields ?? [])
    .map(field => ({ field, label: fieldLabels[field] ?? field }));
  const quantityCheck = prefill?.quantityCheck ?? (prefill?.quantityMismatch
    ? { status: 'mismatch' as const, message: 'Review: the extracted quantity differs '
        + 'from the entered PO quantity. This is a warning, not a rejection.' }
    : { status: 'not_checked' as const, message: 'No quantity comparison was returned.' });
  return <>
    <header>
      <div><h1>Supplier Portal · AI workspace</h1>
        <small>prototype using sample SAP and Infor LN records</small></div>
      <span className="pill">{mode}</span>
    </header>
    <main>
      <section className="card">
        <h2>Buyer · sourcing requests</h2>
        <p className="sub">Select a request to inspect the coded offer ranking.</p>
        {loadError && <p className="error">{loadError}</p>}
        <div className="list">
          {requests.length === 0 && !loadError && 'Loading…'}
          {requests.map(request => <button
            key={request.id} type="button"
            className={`request ${selected?.id === request.id ? 'active' : ''}`}
            onClick={() => void selectRequest(request)}>
            <strong>{request.id} · {request.sourceErp}</strong>
            <span>{request.part} · {request.status}</span>
          </button>)}
        </div>
      </section>
      <section className="card">
        <h2>Compare &amp; draft award</h2>
        <p className="sub">{selected
          ? `${selected.id} · ${selected.part} · need by ${selected.needByDate}`
          : 'Select a request on the left.'}</p>
        {compareError && <p className="error">{compareError}</p>}
        {selected && !comparison && !compareError && <p>Loading…</p>}
        {comparison && offers.length === 0 &&
          <p className="muted">{comparison.message ?? 'No offers yet.'}</p>}
        {offers.length > 0 && <>
          <div className="tablewrap"><table><thead><tr>
            <th>Rank</th><th>Supplier</th>
            <th>{fx ? 'Offer (original)' : 'Total'}</th>
            {fx && <th>{fx.baseCurrency} comparison</th>}
            <th>Delivery</th><th>On time</th>
          </tr></thead><tbody>{offers.map(offer => <tr
            key={offer.supplierId}
            className={offer.meetsNeedBy ? (offer.rank === 1 ? 'top' : '') : 'late'}>
            <td>{offer.rank ?? '—'}</td><td>{offer.supplierName}</td>
            <td>{offer.currency} {money(offer.totalPrice, offer.currency)}</td>
            {fx && <td>{offer.comparisonTotal == null ? '—' : <>
              {fx.baseCurrency} {money(offer.comparisonTotal, fx.baseCurrency)}
              {offer.currency !== fx.baseCurrency && offer.exchangeRateToComparison != null
                && <small className="muted"><br />at {offer.exchangeRateToComparison}
                  {' '}{fx.baseCurrency}/{offer.currency}</small>}
            </>}</td>}
            <td>{offer.promisedDate}</td>
            <td>{offer.meetsNeedBy ? 'Yes' : 'Late'}</td>
          </tr>)}</tbody></table></div>
          {currencyReview
            ? <div className="notice warn">
              <strong>Currency comparison needs review</strong>
              <p>{comparison?.message}</p>
            </div>
            : fx
              ? <div className={`notice ${fx.approved ? '' : 'warn'}`}>
                <strong>{fx.approved
                  ? 'Converted comparison · approved exchange rate'
                  : 'Provisional ranking · demo exchange rate'}</strong>
                <p className="rate">{fxRateText}</p>
                {!fx.approved && <p>{fx.label ? `${fx.label}.` : 'Sample data, not a live or approved rate.'}
                  {' '}Treat this order as provisional until the main backend supplies an
                  approved rate.</p>}
                <p>Offers that meet the need-by date rank first; among them the lowest
                  {' '}{fx.baseCurrency} comparison value wins, then the earliest delivery. Each
                  offer and the purchase order keep their original currency.</p>
              </div>
              : <div className="notice">Ranking is computed by code: lowest total price
                among on-time offers, then earliest delivery.</div>}
          {awardable ? <>
            <label htmlFor="supplier">Choose a supplier</label>
            <select id="supplier" value={supplierId}
              onChange={event => { setSupplierId(event.target.value); clearAward(); }}>
              {currencyReview && <option value="">Select a supplier…</option>}
              {offers.map(offer => <option key={offer.supplierId} value={offer.supplierId}>
                {offer.supplierName} · {offer.currency}{offer.meetsNeedBy ? '' : ' · late'}
              </option>)}
            </select>
            <label htmlFor="reason">{currencyReview
              ? 'Reason for this choice (required: no ranking across currencies)'
              : 'Reason when choosing outside the recommendation'}</label>
            <input id="reason" value={reason}
              onChange={event => { setReason(event.target.value); clearAward(); }}
              placeholder={currencyReview
                ? 'Explain how the offers were compared'
                : 'Optional until an exception is selected'} />
            <p><button type="button" disabled={!supplierId}
              onClick={() => void prepareAward()}>
              Prepare award draft</button></p>
          </> : <div className="notice warn">
            <strong>{historical
              ? 'Historical comparison · no award draft'
              : 'Not ready for award · comparison only'}</strong>
            <p>{comparison?.awardBlockedReason ?? 'This request cannot be awarded.'}</p>
          </div>}
        </>}
        {awardError && <p className="error">{awardError}</p>}
        {award && (!award.draft
          ? <p className="error">{award.message ?? 'Cannot draft award.'}</p>
          : <div className="notice warn">
            <strong>{confirmation
              ? 'Draft only · confirmed in this demo (not sent to ERP)'
              : 'Draft only · awaiting buyer confirmation'}</strong>
            <p>{award.awardTo?.supplierName} · {!award.justificationRequired
              ? `Top recommendation${award.rankingProvisional ? ' (provisional ranking)' : ''}.`
              : `${award.rank === null ? 'No ranking across currencies' : 'Outside the recommendation'}: ${
                !award.justificationMissing
                  ? 'reason recorded for confirmation.'
                  : award.justificationProvided?.trim()
                    ? award.justificationProblem ?? 'the reason is not specific enough.'
                    : 'a reason is required before confirmation.'}`}</p>
            {award.warnings?.length ? <p>{award.warnings.join(' ')}</p> : null}
            {award.erpCallOnConfirm && <>
              <strong>Proposed ERP action after buyer confirmation (not executed)</strong>
              <ErpCallSummary call={award.erpCallOnConfirm}
                supplierName={award.awardTo?.supplierName} />
            </>}
            {!confirmation && <>
              <p><button type="button" disabled={blocker !== null}
                onClick={confirmAward}>Confirm award (demo)</button></p>
              {blocker && <p className="muted">{blocker}</p>}
            </>}
          </div>)}
        {confirmation && <div className="notice success" role="status">
          <strong>Demo confirmation only — no ERP purchase order was created.</strong>
          <p>Award confirmed in this demo for {confirmation.supplierName}
            {' '}({confirmation.supplierId}) on request {confirmation.requestId}.</p>
          {confirmation.reason && <p>Reason recorded: {confirmation.reason}</p>}
          <p className="muted">Kept in this page only. Nothing was sent to SAP or Infor LN and
            no sample record was changed; refreshing or choosing another request clears it.</p>
        </div>}
      </section>
      <section className="card">
        <h2>Buyer · AI assistant</h2>
        <p className="sub">Ask about requests, responses, inspections or ERP documents.</p>
        <div className="feed" ref={feedRef} aria-live="polite">
          {messages.map((message, index) => <div key={index}
            className={`msg ${message.role}`}>{message.text}</div>)}
        </div>
        <label htmlFor="question">Your question</label>
        <div className="row">
          <input id="question" value={question}
            onChange={event => setQuestion(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter') void ask(); }}
            placeholder="Compare responses for REQ-0007" />
          <button type="button" disabled={asking} onClick={() => void ask()}>Ask</button>
        </div>
        <p className="muted">The assistant reads MCP tools. Any award is a draft for buyer review.</p>
      </section>
      <section className="card">
        <h2>Supplier · packing-list pre-fill</h2>
        <p className="sub">Upload a PDF or image to review extracted shipment fields.</p>
        <label htmlFor="packing">Packing list / delivery note</label>
        <input id="packing" type="file" accept=".pdf,.png,.jpg,.jpeg,.webp"
          onChange={event => setFile(event.target.files?.[0] ?? null)} />
        <label htmlFor="poQty">PO quantity · manual sample input</label>
        <input id="poQty" type="number" min="0" value={poQty}
          onChange={event => setPoQty(event.target.value)}
          placeholder="Optional: type a quantity to compare" />
        <p className="muted">Typed by hand for this demo. It is not fetched from SAP, LN
          or a database.</p>
        <p><button type="button" disabled={extracting} onClick={() => void extract()}>
          Extract draft fields</button></p>
        {extracting && <p>Extracting…</p>}
        {prefillError && <p className="error">{prefillError}</p>}
        {prefill && <>
          <div className="notice">
            <strong>Draft for supplier review</strong>
            <p>{prefill.note ?? 'The supplier checks every value and completes any missing '
              + 'fields; nothing has been created or posted.'}</p>
          </div>
          <div className="tablewrap"><table><thead><tr>
            <th>Field</th><th>Extracted value</th>
          </tr></thead><tbody>{Object.keys(fieldLabels).map(name => {
            const missing = prefill.unreadableFields.includes(name);
            return <tr key={name} className={missing ? 'late' : ''}>
              <td>{fieldLabels[name]}</td>
              <td>{missing
                ? <strong>Not readable · enter by hand</strong>
                : showValue(prefill.fields[name])}</td>
            </tr>;
          })}</tbody></table></div>
          {manualEntry.length > 0 && <div className="notice warn">
            <strong>Complete by hand before submitting</strong>
            <p>{manualEntry.map(m => m.label).join(', ')}</p>
          </div>}
          <div className={`notice ${quantityCheck.status === 'mismatch' ? 'warn' : ''}`}>
            <strong>{quantityCheck.status === 'mismatch'
              ? 'Quantity warning · review'
              : quantityCheck.status === 'match'
                ? 'Quantity matches entered PO quantity'
                : 'Quantity not compared'}</strong>
            <p>{quantityCheck.message}</p>
            {prefill.poQuantityNote && <p className="muted">{prefill.poQuantityNote}</p>}
          </div>
        </>}
      </section>
    </main>
  </>;
}
