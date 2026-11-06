# Shared Field Service Visit for several Service Jobs (v1)

Status: BA-approved 2026-10-29 (decisions Q1-Q8), implemented in `warranty_management_fsm`
18.0.1.3.0 and `warranty_management_mrf` 18.0.1.9.3; tested on `wt_p5_mrf`.

## Requirement

Several existing, compatible Service Jobs get ONE shared Field Service visit. The jobs are not
merged and no job is created: each keeps its ID, status, warranty case, warranty card, free
services, worksheets, MRFs, materials, costs and history, and is completed on its own.

## Workflow

1. Warranty > Service Jobs (list): select two or more jobs, then Action > **Create Merged Field
   Service Visit** (Helpdesk users).
2. Wizard: Planned Visit Date, Main Technician, Support Technicians.
3. All or nothing (one savepoint, jobs locked `FOR UPDATE NOWAIT`):
   * every job gets the date and technicians; Draft jobs pass Prepare for Confirmation;
   * every job passes the Confirm Service Job checks and the eligibility revalidation (Q41);
   * one Field Service task is created (`warranty_shared_job_ids`, the free services of all
     jobs, one line per job); every job is confirmed onto it (worksheets per job, services
     Job Created, case Job Created, history notes).
4. On the visit, tab **Service Jobs on this Visit**: **Complete** / **Not Completed** per job.

## Rules

| Rule | Implementation |
|---|---|
| Q1 job types | Standard Warranty jobs only (case-origin and service-origin); chargeable and inspection jobs keep their own visit. |
| Q2 states | Draft or Planned, no visit yet. |
| Compatibility | One company, one customer (commercial partner), same service site (`warranty_same_site`), each job with ticket and case. Several warranty cards: allowed. |
| Q3 tickets | Different tickets allowed; the visit's ticket is set only when all jobs share it (constraint). |
| Timer | One timer starts every job without an outcome (its own services / worksheets only). |
| Complete (per job) | The 4.7 checks of the job (its worksheets, its free services, hold and MRF blockers, sign-off, timer stopped); only its services are consumed; its case completed. |
| Q4 sign-off | One customer signature on the visit; its signer is kept on every completed job line and in each job's completion note. |
| Q5 Not Completed / Hold / Cancel | Only that job: its line gets the outcome, the job follows the existing flow (Incomplete -> Plan Next Visit creates its own single-job visit; Hold blocks only its completion; Cancel Job releases only its services). |
| Q7 closure | The visit closes when every line has an outcome: Done if at least one job was completed on it, else Cancelled. |
| Q8 batch | Jobs with an open shared visit are refused by batch completion. |
| MRF | MRFs are created / linked from the Service Job (job + shared visit); the visit's own MRF and material-usage buttons refuse ("use the Service Job"). Material blockers apply per job. |
| Security | Helpdesk users create the visit; company record rules on jobs and lines; lines written only by the visit actions (marker); the single-job workflow is unchanged. |

## v1 limitations

* **Timesheets / labour cost:** timesheets stay on the shared visit and are **not allocated**
  to the jobs (no labour time / cost per job in reports). Job-level material costs are kept.
* Chargeable and inspection jobs cannot join a shared visit.
* No batch completion for shared visits; no adding / removing a job after creation (cancel the
  job instead).
* The visit-level outcome fields stay empty on shared visits: outcomes are on the job lines.
* Material usage is recorded from the Service Job, not from the shared visit.
