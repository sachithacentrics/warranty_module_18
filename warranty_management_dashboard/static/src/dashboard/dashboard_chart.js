/** @odoo-module **/

import { Component, useEffect, useRef } from "@odoo/owl";

/**
 * One Chart.js chart (Odoo's own web.chartjs_lib bundle). `config` is a plain object built by
 * the dashboard; a new config object re-draws the chart. A click on a bar / slice calls
 * `onSegmentClick(index, datasetIndex)`.
 */
export class WarrantyDashboardChart extends Component {
    static template = "warranty_management_dashboard.Chart";
    static props = {
        config: Object,
        onSegmentClick: { type: Function, optional: true },
        height: { type: Number, optional: true },
        label: { type: String, optional: true },
    };
    static defaultProps = { height: 240 };

    setup() {
        this.canvasRef = useRef("canvas");
        useEffect(
            () => {
                this.draw();
                return () => this.chart && this.chart.destroy();
            },
            () => [this.props.config]
        );
    }

    draw() {
        const canvas = this.canvasRef.el;
        if (!canvas || !window.Chart) {
            return;
        }
        const style = getComputedStyle(canvas.parentElement);
        const text = style.color;
        const font = { size: 12, family: style.fontFamily };
        const legendFont = { size: 12.5, weight: "500", family: style.fontFamily };
        const grid = style.getPropertyValue("--o-wd-grid") || "rgba(0,0,0,0.08)";
        const { type, data, options = {} } = this.props.config;
        if (type === "doughnut") {
            // Segment borders in the panel colour (white in light mode, dark in dark mode).
            const panel = canvas.closest(".o_wd_panel") || canvas.parentElement;
            const background = getComputedStyle(panel).backgroundColor;
            for (const dataset of data.datasets) {
                dataset.borderColor = background;
            }
        }
        const scales = {};
        if (type === "bar" || type === "line") {
            const horizontal = options.indexAxis === "y";
            const valueAxis = horizontal ? "x" : "y";
            const labelAxis = horizontal ? "y" : "x";
            scales[valueAxis] = {
                beginAtZero: true,
                stacked: !!options.stacked,
                ticks: { color: text, font, precision: options.money ? undefined : 0,
                         callback: options.tickFormat },
                grid: { color: grid },
                border: { display: false },
            };
            scales[labelAxis] = {
                stacked: !!options.stacked,
                ticks: { color: text, font, autoSkip: true, maxRotation: 0 },
                grid: { display: false },
                border: { display: false },
            };
        }
        this.chart = new window.Chart(canvas, {
            type,
            data,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 250 },
                indexAxis: options.indexAxis || "x",
                cutout: type === "doughnut" ? "64%" : undefined,
                scales,
                layout: { padding: 4 },
                plugins: {
                    legend: {
                        display: options.legend !== false,
                        // Legend beside a doughnut only where the panel is wide enough.
                        position: type === "doughnut" && canvas.parentElement.clientWidth >= 480
                            ? "right" : "bottom",
                        labels: { color: text, font: legendFont, boxWidth: 12, boxHeight: 12,
                                  usePointStyle: true, pointStyle: "rectRounded", padding: 14 },
                    },
                    tooltip: {
                        bodyFont: font,
                        titleFont: { ...font, weight: "600" },
                        callbacks: options.tooltipFormat
                            ? { label: (ctx) => options.tooltipFormat(ctx) }
                            : {},
                    },
                },
                onHover: (event, elements) => {
                    event.native.target.style.cursor =
                        elements.length && this.props.onSegmentClick ? "pointer" : "default";
                },
                onClick: (event, elements) => {
                    if (elements.length && this.props.onSegmentClick) {
                        this.props.onSegmentClick(elements[0].index, elements[0].datasetIndex);
                    }
                },
            },
        });
    }
}
