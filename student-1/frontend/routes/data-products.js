import { collection } from "../core/api.js";
import { append, el } from "../core/dom.js";
import { formatNumber, researchAreaLabel } from "../core/formats.js";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js";
import { errorState } from "../components/states.js";
import { cell, makeTable } from "../components/tables.js";

export function createDataProductRoutes({ view, request, loading, rerender }) {
  async function renderDataProducts(id = "") {
    loading("Loading data-product catalogue");
    try {
      if (id) return renderDetail(id);
      const products = collection((await request("data-products")).body);
      view.replaceChildren();
      append(view, pageHeading(
        "Release 0 provider contracts",
        "Data-product catalogue",
        "Stable, bounded products available to PropertyScope features. Licence-controlled products remain discoverable without exposing restricted artifacts.",
      ));
      append(view, panel(
        `${products.length} registered products`,
        "Accessible table view of builders, schemas, ownership, capability, and accepted state",
        makeTable(
          [
            { label: "Dataset / product" },
            { label: "Owner" },
            { label: "Builder" },
            { label: "Schema" },
            { label: "Maximum rows" },
            { label: "Capability" },
            { label: "Accepted release" },
            { label: "Download" },
          ],
          products,
          (product) => {
            const row = el("tr");
            const productLink = el("a", "", product.display_name || product.dataset_id);
            productLink.href = `#data-products/${encodeURIComponent(product.dataset_id)}`;
            const productCell = el("span", "primary-cell");
            append(productCell, productLink, el("span", "sub-cell", product.dataset_id));
            append(
              row,
              cell(productCell, "primary-cell"),
              cell(researchAreaLabel(product.target_feature)),
              cell(`${product.builder_key} ${product.builder_version}`),
              cell(product.product_schema_version, "mono"),
              cell(formatNumber(product.max_rows), "numeric"),
              cell(badge(product.capability_state)),
              cell(product.latest_accepted_release?.release_version || "No contract-valid release yet"),
              cell(product.download_permitted ? "Permitted" : "Restricted"),
            );
            return row;
          },
          "Registered PropertyScope data products",
        ),
      ));
    } catch (error) {
      view.replaceChildren(errorState(error, rerender));
    }
  }

  async function renderDetail(id) {
    const product = (await request(`data-products/${encodeURIComponent(id)}`)).body;
    view.replaceChildren();
    append(view, pageHeading(
      "Data-product contract",
      product.display_name || product.dataset_id,
      `${researchAreaLabel(product.target_feature)} · ${product.product_schema_version}`,
    ));
    const accepted = product.latest_accepted_release;
    append(view, panel(
      "Registered publication path",
      "The generic release API remains unchanged when a future product is registered",
      detailList([
        ["Dataset", product.dataset_id],
        ["Job / import", `${product.job_profile} / ${product.import_profile}`],
        ["Builder", `${product.builder_key} ${product.builder_version}`],
        ["Schema", product.product_schema_version],
        ["Ordering", product.ordering_rule],
        ["Scope profiles", product.supported_scope_profiles.join(", ")],
        ["Bounds", `${formatNumber(product.max_rows)} rows / ${formatNumber(product.max_bytes)} bytes`],
        ["Redistribution", `${product.redistribution_decision} (${product.download_permitted ? "download permitted" : "download restricted"})`],
        ["Capability", badge(product.capability_state)],
        ["Accepted release", accepted ? technicalDetails(accepted, "Inspect accepted release") : "No contract-valid release yet"],
        ["Known limitations", product.known_limitations.join(" ")],
      ]),
    ));
  }

  return { renderDataProducts };
}
