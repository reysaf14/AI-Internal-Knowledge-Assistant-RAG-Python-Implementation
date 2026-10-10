# PRD — Toko Makmur Jaya Internal Knowledge Assistant

- Delivery lane: `PROFESSIONAL`
- Scope version: `0.3`
- PRD version: `1.1`
- Date: `2026-09-14`
- Status: `APPROVED`
- Approved by: `Human`
- Approval date: `2026-09-14`

## Background

Operational SOPs, customer policies, complaint guides, and internal policies for Toko Makmur Jaya have been documented but are scattered and rarely referenced after initial training. As a result, employees frequently ask managers for answers and may provide inconsistent information.

This project provides an internal Q&A assistant for cashiers, sales associates, and warehouse staff. The assistant must answer based on official documents, cite correct sources, and admit when the corpus does not support an answer. Employees remain human-in-the-loop before passing information to customers.

Business objectives:

- reduce repetitive interruptions to managers;
- improve consistency of employee answers;
- simplify use and updating of official knowledge;
- prevent unsupported policy answers.

## Data & Operational Boundary

| Area | Data Category | Allowed Representation | Source / Destination and Owner |
|---|---|---|---|
| Policy corpus | `Confidential` | `minimized-and-masked`; only material cleansed of direct identities, credentials, signatures, personal contacts, and individual records | Official source is all ratified documents in `/docs`; baseline 26 Markdown files `00`–`25`. Owner/manager ratifies corpus changes |
| Dev/eval questions and answers | `Internal` if synthetic; otherwise follows actual data class | `synthetic` by default | Fixtures and reports owned by delivery team; answer keys and sources ratified by owner/manager before evaluation |
| Candidate `QA_Dataset_15_Pasangan.csv` | `Internal` because all content confirmed synthetic by Human on `2026-09-13` | `synthetic`; may be processed into a working copy matching the rubric | Not yet an approved eval set until 12+3 composition and answer keys are adjusted and ratified |
| Operational employee questions | Potentially `Confidential` or `Restricted` depending on content | Limited to general policy questions; users must not input individual records, transaction data, or customer/employee identities | Entered via shared internal Telegram channel and produce answers to employees |
| Credentials and secret configuration | `Restricted` | `blocked` from prompts, repository, fixtures, screenshots, reports, and project state | Human/client provisions via approved credential/runtime storage at technical stage |
| HR/customer records, payment data, production payloads | `Restricted` | `blocked` | Out of scope; new needs for this data return to Human for classification and scope change |

Owner/manager ratifies corpus and is initial operations owner until Human designates another party. Operator only loads pre-ratified documents. Added or replaced documents must be recorded as part of the active corpus before reload.

No per-employee authentication in this scope. One bot shared by internal employees. Telegram runtime uses polling. Conversation content is not stored by the application; processing only occurs during active request. Minimal technical metadata may be stored if needed for offset/update, idempotency, observability, or diagnosis, but must not contain question/answer content, user identities, usernames, or chat IDs.

## Implementation & Runtime Boundary

Implementation uses full application code and does not use n8n or similar workflow orchestration platforms. Delivery has two code entry points: knowledge base reload and Telegram Q&A runtime. The first runtime targets local machines and must be portable to VPS via conceptually identical configuration. Model components are written generically so local experiments can use available models without locking the PRD to a specific vendor or technology.

## User Stories

- As a store employee, I want to ask questions in everyday language so I can find relevant policies without always contacting the manager.
- As a store employee, I want to see the source document name so I can verify the basis of the answer before passing it to a customer.
- As a store employee, I want the assistant to admit when information is not found so I don't follow made-up answers.
- As an owner/manager, I want to update the official corpus so answers follow current SOPs and policies.
- As an owner/manager, I want to see evaluation results and per-question failures so I can transparently assess fitness for use.

## Required Features

| ID | Business Need | Priority | Agreed Outcome |
|---|---|---|---|
| `REQ-001` | Knowledge base uses all current official documents and can be reloaded after updates | Mandatory | Baseline covers 26 Markdown documents `00`–`25`; operator can run reload and identify the active corpus |
| `REQ-002` | Internal employees can send questions and receive answers via shared Telegram bot | Mandatory | Every valid question produces one response readable by employees through polling runtime; no per-employee authentication/personalization |
| `REQ-003` | Answer content is based only on official corpus | Mandatory | Content accuracy reaches at least `12/15` on approved eval set per binary rubric not requiring word-for-word match |
| `REQ-004` | Supported answers cite correct sources | Mandatory | All 12 supported questions cite at least one correct supporting document name; any additional sources must also be relevant |
| `REQ-005` | Assistant does not fabricate when corpus does not support an answer | Mandatory | All 3 unsupported questions produce a "don't know" statement, without policy claims or fake sources |
| `REQ-006` | Response available within reasonable time for operational use | Mandatory | Each of 15 eval questions receives a response within `<5.0 seconds`, measured from app receipt of question to successful Telegram answer delivery |
| `REQ-007` | Deliverables can be prepared, evaluated, and maintained by designated operator | Mandatory | Full application code with two operational entry points—knowledge base reload and Q&A bot runtime—plus local/VPS setup guide, document replacement guide, per-question evaluation results with failure notes, and sanitized conversation demo |

## Optional Features

No optional features in this version. POS/realtime stock integration, per-employee authentication, personalization, direct customer access, and out-of-corpus answers remain out of scope.

## Success Criteria

Approved eval set consists of 15 synthetic questions:

- 12 supported questions: 3 operational SOPs, 3 customer FAQs, 2 complaint guides, 3 internal policies, and 1 company profile;
- 3 unsupported questions whose answers are deliberately absent from corpus;
- answer keys and source documents defined before testing and ratified by owner/manager.

Content rubric uses binary `PASS`/`FAIL`. Supported answer passes if all required facts are conveyed, do not contradict corpus, and add no unsupported policy claims. Unsupported answer passes only if it states information not found/unknown, does not guess, and cites no fake sources.

| Requirement | Success Criterion | Safe Measurement Basis |
|---|---|---|
| `REQ-001` | All 26 baseline documents recorded as active corpus and reload can produce latest identifiable corpus version | Sanitized file name inventory and process metadata; no credentials or raw content in reports |
| `REQ-002` | 15 eval questions each produce one readable Telegram response | Synthetic fixtures and sanitized polling execution evidence |
| `REQ-003` | At least 12 of 15 answers pass content rubric (`≥80%`) | Per-question assessment against approved answer key; wording need not be identical |
| `REQ-004` | Source accuracy `12/12` for supported questions | Comparison of cited document names with approved sources; any additional sources must be relevant |
| `REQ-005` | Abstention `3/3` for unsupported questions | Check that answer states don't know, makes no policy claim, and fabricates no sources |
| `REQ-006` | Response time `<5.0 seconds` on `15/15` questions | Timestamp delta from app receipt of question to successful response delivery; report each duration |
| `REQ-007` | All deliverables available and reviewable by owner/manager | Code entry point list, local/VPS usage guide, document replacement guide, evaluation report, sanitized demo; no credentials or raw payloads |

Failure on hard gates for source, abstention, or response time cannot be masked by aggregate accuracy score. Evaluation results must still show per-question status and failure notes.

Dataset `QA_Dataset_15_Pasangan.csv` provided by Human contains 15 unique rows with columns `Question`, `Correct_Answer`, and `Source_Document`; structural check found no empty cells. Rows 3, 7, 8, and 15 reference documents outside the official `00–25` corpus. The first three will become unsupported scenarios, while row 15 must be replaced with a supported question from document `00` so final composition becomes 12 supported + 3 unsupported. Human has confirmed all dataset content as synthetic, so a working copy may be prepared at the next stage. Source file at `D:/QA_Dataset_15_Pasangan.csv` is unchanged and candidate is not yet an approved eval set until adjustment and answer key ratification.

## Revision History

| Version | Date | Changes | Requested By |
|---|---|---|---|
| `1.0` | `2026-09-13` | Initial PRD based on approved Scope Card `0.3`; establishes 26-document corpus and 12 supported + 3 unsupported rubric | Human |
| `1.1` | `2026-09-14` | Establishes full code implementation without n8n, Telegram polling, no-conversation-storage policy, operational entry points, and candidate dataset 12+3 status | Human |