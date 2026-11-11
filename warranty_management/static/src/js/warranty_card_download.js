import { registry } from "@web/core/registry";
import { download } from "@web/core/network/download";

/**
 * Download PDF of the warranty card: the single-use ticket link is downloaded in the
 * background (one request, so one download record), then the action closes like any button
 * action, so the form reloads with the new Download Count and chatter note.
 */
async function warrantyCardDownloadPdf(env, action) {
    await download({ url: action.params.url, data: {} });
    return { type: "ir.actions.act_window_close" };
}

registry.category("actions").add("warranty_card_download_pdf", warrantyCardDownloadPdf);
