# 23 – AMC User Guide

## 1. Set up (AMC Manager / Administrator)

1. **Settings > AMC**: Default Plan, Default Billing Plan, Default Start Criteria, Renewal Rule,
   Alert Days, **Activation Trigger** (Sales Order confirmation or payment of the first invoice), AMC
   Service Product. *Warranty Integration* (with `amc_management_warranty`): **AMC Auto-create
   Mode** (None / Draft AMC Opportunity / Draft AMC Contract) and **Offer AMC on Warranty Expiry**.
2. **Configuration > Billing Plans**: Annual Upfront, Quarterly / Monthly in Advance, Per
   Preventive Visit (or your own).
3. **Configuration > AMC Plans**: e.g. *Retail AMC*: Visit Count 3, 3 visits per Year, Included Free
   Services 1, Visit Planning Alert-Driven, Alert Days 7, Grace 15 days, Renewal Notice 30 days,
   Duration 12 months, Billing Plan, Start Criteria; Applicability (pricelists, products,
   categories).
4. **Configuration > Pricing Formulas**: create a version (method and amounts, min / max,
   rounding), check the sample, **Activate**. Changes later: **New Version**.

## 2. Sell a contract (AMC Coordinator)

1. **Sales > Contracts > New** (or from an Opportunity *Won*, or *Convert to AMC* on a warranty
   card): customer, site, plan, covered equipment (product, serial or warranty unit, quantity,
   equipment value).
2. **Calculate Price** – optional **Request Override** (an AMC Approver decides).
3. **Create Quotation** → confirm the Sales Order (Sales).
   * Trigger *Sales Order confirmation*: the contract is **Active** at once.
   * Trigger *payment*: the contract waits in **Awaiting Payment**; click **Create Invoice**, post it
     (Accounting) and register the payment → **Active**.
4. On activation the **AMC Visits** smart button lists the preventive visits (with due dates) and
   the included free services of every covered unit.

## 3. Bill

Billing periods are released automatically on their date (advance: period start; arrears: period
end; per visit: when the visit is completed). **Create Invoice** creates the draft invoice of the
released periods (also possible from the Sales Order). Nothing is posted automatically.

## 4. Plan and execute visits

* **Services > AMC Visits** (list, kanban, calendar): filters Due / Overdue / Planned; the
  responsible gets a To-Do *Alert Days* before each due date.
* **With the service chain** (`amc_management_service`): select Pending visits of one contract and
  site → **Create Service Request** → Helpdesk ticket + AMC case → Check Eligibility → Approve →
  Prepare Service Job → plan date and technicians → Confirm → the technician works on the Field
  Service visit (worksheet per AMC visit, usage reading if required, customer signature) → Complete
  Visit. The AMC visits are completed automatically. A Helpdesk ticket of the customer shows
  *Pending AMC Services*; *Add AMC Services to this Ticket* links them to that request.
* **Without the service chain**: set the Planned Date, then **Complete** (date, notes, usage).
* Missed visits (after the grace period, if enabled) can be **Reopened** by a Manager.

## 5. Contract changes

* **Put On Hold** (reason) / **Resume** – Manager.
* The contract becomes **Expiring** at the renewal notice; **Renew** prepares a Draft renewal
  (Auto Offer plans: automatically). Sell it like a new contract. The old contract becomes
  **Renewed**; without renewal it is **Closed** after its end date (or **Close Contract** now).
* **Cancel Contract** only before activation.

## 6. Reports

**Reporting > AMC Visit Schedule** (pivot by plan × month × status, graph, list); **Print Visit
Schedule** on a contract.
