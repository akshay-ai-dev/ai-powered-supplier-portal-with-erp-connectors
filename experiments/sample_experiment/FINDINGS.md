# Findings: <feature name>

Work out everything in this document when designing any feature, before building it.

**Feature:** one or two sentences on what the feature does and who uses it.

---

## 1. High-level diagram

A simple line diagram of the system or feature. It should show all three of the following at a glance: data movement, data storage and data transformation.

```
 [Source]  ──(what data, how)──▶  [Component A]  ──(what data, how)──▶  [Component B]  ──▶  [Destination]
                                   transform: filter                     transform: aggregate
                                   stored in: RAM                        stored in: Disk
```

---

## 2. Data movement

Where, how and what data comes **into**, goes **through** and goes **out of** the system.

| Stage | From → To | What data | How (protocol / format) |
|-------|-----------|-----------|-------------------------|
| In | | | e.g. REST over HTTPS, JSON |
| Through | | | e.g. in-process function call |
| Out | | | e.g. SQL insert, SMTP, HTTP response |

---

## 3. Data storage

Where the data is stored at each point of its movement.

| Stage | Stored in (CPU / RAM / Disk) | What is stored | How long it lives | Rough size |
|-------|------------------------------|----------------|-------------------|------------|
| | CPU (registers / cache) | | | |
| | RAM (process memory, in-memory cache) | | | |
| | Disk (database, files) | | | |

---

## 4. Data transformation

How the data is transformed along the way.

| Step | Input | Operation (algorithm / map / filter / aggregation / sort / join …) | Output |
|------|-------|--------------------------------------------------------------------|--------|
| 1 | | | |
| 2 | | | |

---

## 5. Non-functional questions

Answer these in this order of priority.

### 5.1 Availability

- What must stay up for this feature to work? List every dependency.

### 5.2 Latency

- How long does one request or operation take, end to end?
- Where is that time spent (network, ERP call, AI call, DB, disk)?

### 5.3 Throughput

- How many requests, records or files per second (or per minute) must it handle?

### 5.4 Reliability

- How can it fail (bad input, timeout, partial write, duplicate request)?
- How is each failure detected and handled (retries, idempotency keys, validation)?
- Can data be lost or duplicated? How is that prevented?

