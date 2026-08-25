import { collection } from "../core/api.js";
import { append, el } from "../core/dom.js";
import { displayName, formatNumber, humanise, researchAreaLabel } from "../core/formats.js?v=18";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js?v=17";
import { errorState } from "../components/states.js";
import { cell, makeTable } from "../components/tables.js";

export function createDataProductRoutes({ view, request, loading, rerender }) {
  async function renderDataProducts(id = "") {
    loading("Loading data product definitions");
    try {
      if (id) return renderDetail(id);
      const products = collection((await request("data-products")).body);
      view.replaceChildren();
      append(view, pageHeading(
        "Advanced data settings",
        "Dataset publishing settings",
        "Configuration used to publish data to other PropertyScope research areas.",
      ));
      append(view, panel(
        `${products.length} registered datasets`,
        "Publishing schemas and current versions",
        makeTable(
          [
            { label: "Dataset" },
            { label: "Research area" },
            { label: "Publishing process" },
            { label: "Schema" },
            { label: "Portable product limit" },
            { label: "Availability" },
            { label: "Published version" },
            { label: "Download" },
          ],
          products,
          (product) => {
            const row = el("tr");
            const productLink = el("a", "", displayName(product.display_name || product.dataset_id));
            productLink.href = `#data-products/${encodeURIComponent(product.dataset_id)}`;
            const productCell = el("span", "primary-cell");
            append(productCell, productLink, el("span", "sub-cell", displayName(product.dataset_id)));
            append(
              row,
              cell(productCell, "primary-cell"),
              cell(researchAreaLabel(product.target_feature)),
              cell(`${product.builder_key} ${product.builder_version}`),
              cell(product.product_schema_version, "mono"),
              cell(formatNumber(product.max_rows), "numeric"),
              cell(badge(humanise(product.capability_state))),
              cell(product.latest_accepted_release?.release_version || "No published version yet"),
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
      "Publishing settings",
      displayName(product.display_name || product.dataset_id),
      `${researchAreaLabel(product.target_feature)} · ${product.product_schema_version}`,
    ));
    const accepted = product.latest_accepted_release;
    append(view, panel(
      "Publication configuration",
      "How this dataset is prepared and shared",
      detailList([
        ["Dataset", displayName(product.dataset_id)],
        ["Update / import profile", `${product.job_profile} / ${product.import_profile}`],
        ["Publishing process", `${product.builder_key} ${product.builder_version}`],
        ["Schema", product.product_schema_version],
        ["Ordering", product.ordering_rule],
        ["Allowed update methods", product.supported_scope_profiles.join(", ")],
        ["Portable product limit", `${formatNumber(product.max_rows)} rows / ${formatNumber(product.max_bytes)} bytes`],
        ["Redistribution", `${product.redistribution_decision} (${product.download_permitted ? "download permitted" : "download restricted"})`],
        ["Availability", badge(product.capability_state)],
        ["Published version", accepted ? technicalDetails(accepted, "Inspect published version") : "No published version yet"],
        ["Known limitations", product.known_limitations.join(" ")],
      ]),
    ));
  }

  return { renderDataProducts };
}
