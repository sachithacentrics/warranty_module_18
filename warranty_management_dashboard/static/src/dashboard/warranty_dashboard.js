/** @odoo-module **/

import { Component, markRaw, onWillStart, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { formatCurrency } from "@web/core/currency";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { WarrantyDashboardChart } from "./dashboard_chart";

// Odoo Plum theme (approved): primary, success, warning, critical, information, neutral.
const C = {
    plum: "#714B67",
    plumLight: "#A98AA0",
    teal: "#168A72",
    amber: "#E3A247",
    red: "#D65B65",
    blue: "#3B7CC4",
    gray: "#9AA0A6",
    slate: "#5F6368",
};
const CARD_STATE_COLORS = {
    draft: C.gray,
    pending_installation: C.amber,
    ready: C.blue,
    confirmed: C.teal,
    suspended: C.plumLight,
    expired: C.red,
    cancelled: C.slate,
};
const DUE_COLORS = { overdue: C.red, due: C.amber, upcoming: C.blue, none: C.gray };
const COST_COLORS = [C.plum, C.blue, C.amber, C.teal, C.plumLight, C.red, C.slate, C.gray];

export class WarrantyDashboard extends Component {
    static template = "warranty_management_dashboard.Dashboard";
    static components = { WarrantyDashboardChart };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            filters: {},
            data: null,
            finance: null,
            loading: true,
            financeLoading: true,
            failureGroup: "product",
            charts: {},
        });
        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.load();
        });
    }

    // ---------------------------------------------------------------- data
    async load() {
        this.state.loading = true;
        const data = await this.orm.call("warranty.dashboard", "get_dashboard_data", [
            this.state.filters,
        ]);
        this.state.filters = data.filters;
        this.state.data = data;
        this.buildCharts();
        this.state.loading = false;
        this.loadFinance(false);
    }

    async loadFinance(refresh) {
        this.state.financeLoading = true;
        const finance = await this.orm.call(
            "warranty.dashboard",
            "get_financial_data",
            [this.state.filters],
            { refresh }
        );
        this.state.finance = finance;
        this.buildFinanceCharts();
        this.state.financeLoading = false;
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

    // ---------------------------------------------------------------- navigation
    async open(key, extra = {}) {
        const action = await this.orm.call("warranty.dashboard", "action_dashboard_open", [
            key,
            this.state.filters,
            extra,
        ]);
        await this.actionService.doAction(action);
    }

    openReport(report) {
        this.actionService.doAction(report.xml_id);
    }

    scrollTo(id) {
        const el = document.getElementById(id);
        if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "center" });
            el.classList.add("o_wd_flash");
            setTimeout(() => el.classList.remove("o_wd_flash"), 1200);
        }
    }

    // ---------------------------------------------------------------- formatting
    get currency() {
        return (this.state.finance && this.state.finance.currency) ||
            (this.state.data && this.state.data.options.currency);
    }

    money(value) {
        const currency = this.currency;
        return currency ? formatCurrency(value || 0, currency.id) : String(value || 0);
    }

    count(value) {
        return value === null || value === undefined ? "—" : String(value);
    }

    total(rows) {
        return (rows || []).reduce((sum, row) => sum + (row.value || 0), 0);
    }

    // ---------------------------------------------------------------- charts
    buildCharts() {
        const charts = this.state.data.charts;
        const result = {};
        if (charts.card_status && charts.card_status.length) {
            result.cardStatus = markRaw({
                type: "doughnut",
                data: {
                    labels: charts.card_status.map((r) => r.label),
                    datasets: [{
                        data: charts.card_status.map((r) => r.value),
                        backgroundColor: charts.card_status.map((r) => CARD_STATE_COLORS[r.key] || C.gray),
                        borderWidth: 2,
                    }],
                },
            });
        }
        if (charts.expiry_trend && this.total(charts.expiry_trend)) {
            result.expiry = markRaw({
                type: "bar",
                data: {
                    labels: charts.expiry_trend.map((r) => r.label),
                    datasets: [{
                        label: _t("Warranties ending"),
                        data: charts.expiry_trend.map((r) => r.value),
                        backgroundColor: C.amber,
                        borderRadius: 4,
                        maxBarThickness: 28,
                    }],
                },
                options: { legend: false },
            });
        }
        if (charts.service_due && this.total(charts.service_due)) {
            const rows = charts.service_due.filter((r) => r.value);
            result.serviceDue = markRaw({
                type: "doughnut",
                data: {
                    labels: rows.map((r) => r.label),
                    datasets: [{
                        data: rows.map((r) => r.value),
                        backgroundColor: rows.map((r) => DUE_COLORS[r.key]),
                        borderWidth: 2,
                    }],
                },
            });
            result.serviceDueRows = markRaw(rows);
        }
        const trend = charts.replacement_trend;
        if (trend && (this.sum(trend.replacements) || this.sum(trend.repeated))) {
            const datasets = [];
            if (trend.replacements) {
                datasets.push({
                    type: "bar",
                    label: _t("Replacements"),
                    data: trend.replacements,
                    backgroundColor: C.plum,
                    borderRadius: 4,
                    maxBarThickness: 22,
                    order: 2,
                });
            }
            if (trend.repeated) {
                datasets.push({
                    type: "line",
                    label: _t("Repeated failure cases"),
                    data: trend.repeated,
                    borderColor: C.red,
                    backgroundColor: C.red,
                    tension: 0.3,
                    pointRadius: 3,
                    order: 1,
                });
            }
            result.trend = markRaw({
                type: "bar",
                data: { labels: trend.months.map((m) => m.label), datasets },
            });
        }
        this.state.charts = Object.assign({}, this.state.charts, result, {
            failure: this.failureConfig(),
        });
    }

    sum(values) {
        return (values || []).reduce((a, b) => a + b, 0);
    }

    get failureRows() {
        const failures = this.state.data && this.state.data.charts.failures;
        if (!failures) {
            return [];
        }
        if (this.state.failureGroup === "category") {
            return failures.categories;
        }
        return failures.products.slice(0, failures.top).map((p) => ({
            label: p.label, value: p.value, extra: { product_ids: [p.id] },
        }));
    }

    failureConfig() {
        const rows = this.failureRows;
        if (!rows.length) {
            return null;
        }
        return markRaw({
            type: "bar",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [{
                    label: _t("Failure cases"),
                    data: rows.map((r) => r.value),
                    backgroundColor: C.plum,
                    borderRadius: 4,
                    maxBarThickness: 18,
                }],
            },
            options: { indexAxis: "y", legend: false },
            rows,
        });
    }

    setFailureGroup(group) {
        this.state.failureGroup = group;
        this.state.charts = Object.assign({}, this.state.charts, { failure: this.failureConfig() });
    }

    buildFinanceCharts() {
        const finance = this.state.finance;
        const result = { cost: null, recovery: null, reserve: null };
        const moneyFormat = (ctx) => `${ctx.dataset.label || ctx.label}: ${this.money(ctx.raw)}`;
        // Cost types only: the vendor recovery is its own "Recovered" figure above the chart.
        const costRows = finance.cost.available
            ? finance.cost.rows.filter((r) => r.key !== "recovery" && r.actual)
            : [];
        if (costRows.length) {
            const rows = costRows;
            result.cost = markRaw({
                type: "bar",
                data: {
                    labels: rows.map((r) => r.label),
                    datasets: [{
                        label: _t("Actual cost"),
                        data: rows.map((r) => r.actual),
                        backgroundColor: rows.map((r, i) => COST_COLORS[i % COST_COLORS.length]),
                        borderRadius: 4,
                        maxBarThickness: 20,
                    }],
                },
                options: { indexAxis: "y", legend: false, money: true,
                           tooltipFormat: (ctx) => `${ctx.label}: ${this.money(ctx.raw)}` },
                rows,
            });
        }
        if (finance.recovery.available && finance.recovery.claims) {
            const r = finance.recovery;
            result.recovery = markRaw({
                type: "bar",
                data: {
                    labels: [_t("Claimed"), _t("Accepted"), _t("Recovered"), _t("Outstanding"),
                             _t("Written off")],
                    datasets: [{
                        label: _t("Amount"),
                        data: [r.claimed_amount, r.accepted_amount, r.recovered_amount,
                               r.outstanding_amount, r.written_off_amount],
                        backgroundColor: [C.plum, C.blue, C.teal, C.amber, C.red],
                        borderRadius: 4,
                        maxBarThickness: 34,
                    }],
                },
                options: { legend: false, money: true, tooltipFormat: moneyFormat },
            });
        }
        if (finance.reserve.available) {
            const r = finance.reserve;
            const values = [r.provision_amount, r.utilization_amount, r.release_amount,
                            r.reversal_amount, r.actual_cost_amount];
            if (values.some((v) => v)) {
                result.reserve = markRaw({
                    type: "bar",
                    data: {
                        labels: [_t("Provisions"), _t("Utilization"), _t("Releases"),
                                 _t("Reversals"), _t("Actual cost")],
                        datasets: [{
                            label: _t("Amount"),
                            data: values,
                            backgroundColor: [C.plum, C.teal, C.blue, C.gray, C.amber],
                            borderRadius: 4,
                            maxBarThickness: 34,
                        }],
                    },
                    options: { legend: false, money: true, tooltipFormat: moneyFormat },
                    keys: ["provision", "utilization", "release", "reversal", "actual_cost"],
                });
            }
        }
        this.state.charts = Object.assign({}, this.state.charts, result);
    }

    // ---------------------------------------------------------------- chart clicks
    onCardStatusClick(index) {
        this.open("card_status", this.state.data.charts.card_status[index].extra);
    }

    onExpiryClick(index) {
        this.open("expiry_trend", this.state.data.charts.expiry_trend[index].extra);
    }

    onServiceDueClick(index) {
        this.open("service_due_chart", this.state.charts.serviceDueRows[index].extra);
    }

    onFailureClick(index) {
        this.open("failures", this.state.charts.failure.rows[index].extra);
    }

    onTrendClick(index, datasetIndex) {
        const trend = this.state.data.charts.replacement_trend;
        const dataset = this.state.charts.trend.data.datasets[datasetIndex];
        const key = dataset.type === "line" ? "repeated_trend" : "replacement_trend";
        this.open(key, { month: trend.months[index].key });
    }

    onCostClick(index) {
        this.open("cost", this.state.charts.cost.rows[index].extra);
    }

    onReserveClick(index) {
        const key = this.state.charts.reserve.keys[index];
        this.open("reserve", { movement_type: key });
    }
}

registry.category("actions").add("warranty_management_dashboard.dashboard", WarrantyDashboard);
