/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Warranty Dashboard: the five areas Warranty Status, Pending Services, Approvals,
 * Replacements and Escalations, with their filters, the Warranty Cards by Status chart and the
 * report shortcuts. All figures come from `warranty.dashboard.get_dashboard_data`; every number
 * and chart bar opens the records it counts.
 */
export class WarrantyDashboard extends Component {
    static template = "warranty_management_dashboard.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({ filters: {}, data: null, loading: true });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const data = await this.orm.call("warranty.dashboard", "get_dashboard_data", [
            this.state.filters,
        ]);
        this.state.filters = data.filters;
        this.state.data = data;
        this.state.loading = false;
    }

    onFilter(key, ev) {
        let value = ev.target.value;
        if (["company_id", "branch_id", "category_id", "expiring_days"].includes(key)) {
            value = value ? parseInt(value) : false;
        }
        this.state.filters[key] = value || false;
        if (key === "company_id") {
            this.state.filters.branch_id = false;
        }
        this.load();
    }

    resetFilters() {
        this.state.filters = {};
        this.load();
    }

    async open(key, extra = {}) {
        const action = await this.orm.call("warranty.dashboard", "action_dashboard_open", [
            key,
            this.state.filters,
            extra,
        ]);
        await this.actionService.doAction(action);
    }

    onKey(ev, key, extra) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.open(key, extra);
        }
    }

    openReport(report) {
        this.actionService.doAction(report.xml_id);
    }

    count(value) {
        return value === null || value === undefined ? "—" : String(value);
    }

    /** Short row labels of the approval types (the full name stays in aria-label). */
    shortLabel(line) {
        const labels = { appr_card_action: "Card actions", appr_download: "Download requests" };
        return labels[line.key] || line.label;
    }

    /** Approval line of a document type (null when the user cannot read it). */
    approval(key) {
        return this.state.data.approvals.lines.find((line) => line.key === key) || null;
    }

    /** Open services of one due indicator ("none": not yet in the alert window). */
    due(key) {
        const line = (this.state.data.services.by_due || []).find((row) => row.key === key);
        return line ? line.value : null;
    }

    /** Bar length of a status line, relative to the largest status count. */
    barWidth(value) {
        const lines = this.state.data.warranty.by_status || [];
        const max = Math.max(1, ...lines.map((line) => line.value));
        return `width: ${Math.max(1.5, (100 * value) / max)}%`;
    }

    get companyName() {
        const companies = this.state.data.options.companies;
        return companies.length === 1 ? companies[0].name : "";
    }
}

registry.category("actions").add("warranty_management_dashboard.dashboard", WarrantyDashboard);
