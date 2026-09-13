import { collection } from "../core/api.js";
import { groupCatalogueItems, presentedName } from "../core/catalogue.js";
import { append, el } from "../core/dom.js";
import { displayName, humanise, researchAreaLabel } from "../core/formats.js";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js";
import { errorState } from "../components/states.js";
import { cell, makeTable } from "../components/tables.js";

export function createDataProductRoutes({ view, request, loading, generationGuard, rerender }) {
  async function renderDataProducts(id = "") {
    const routeEpoch = generationGuard.capture();
    loading("Loading data product definitions");
    try {
      if (id) return await renderDetail(id, routeEpoch);
      const [productResult, presentationResult] = await Promise.all([
        request("data-products"),
        request("catalogue-presentation"),
      ]);
      const products = collection(productResult.body);
      const groups = groupCatalogueItems(products, presentationResult.body, (product) => product.source_key || product.dataset_id);
      if (!routeEpoch.isCurrent()) return;
      view.replaceChildren();
      append(view, pageHeading(
        "Advanced data settings",
        "Dataset publishing settings",
        "Configuration used to publish data to other PropertyScope research areas.",
      ));
      const groupHost = el("div", "catalogue-groups");
      groupHost.setAttribute("aria-label", `${products.length} registered datasets`);
      for (const group of groups) append(groupHost, panel(
        group.label,
        `${group.description} · ${group.items.length} ${group.items.length === 1 ? "dataset" : "datasets"}`,
        makeTable(
          [
            { label: "Dataset" },
            { label: "Research area" },
            { label: "Publishing process" },
            { label: "Schema" },
            { label: "Configured support" },
            { label: "Published version" },
            { label: "Download" },
          ],
          group.items,
          ({ item: product, presentation }) => {
            const row = el("tr");
            const productLink = el("a", "", presentedName(presentation, product.display_name || product.dataset_id));
            productLink.href = `#data-products/${encodeURIComponent(product.dataset_id)}`;
            const productCell = el("span", "primary-cell");
            append(
              productCell,
              productLink,
              presentation?.purpose ? el("span", "sub-cell", presentation.purpose) : null,
              el("span", "sub-cell mono", displayName(product.dataset_id)),
            );
            append(
              row,
              cell(productCell, "primary-cell"),
              cell(researchAreaLabel(product.target_feature)),
              cell(`${product.builder_key} ${product.builder_version}`),
              cell(product.product_schema_version, "mono"),
              cell(badge(humanise(product.capability_state))),
              cell(product.latest_accepted_release?.release_version || "No published version yet"),
              cell(product.download_permitted ? "Permitted" : "Restricted"),
            );
            return row;
          },
          `${group.label} PropertyScope data products`,
        ),
      ));
      append(view, groupHost);
    } catch (error) {
      if (!routeEpoch.isCurrent()) return;
      view.replaceChildren(errorState(error, rerender));
    }
  }

  async function renderDetail(id, routeEpoch) {
    const [productResult, presentationResult] = await Promise.all([
      request(`data-products/${encodeURIComponent(id)}`),
      request("catalogue-presentation"),
    ]);
    const product = productResult.body;
    const group = groupCatalogueItems([product], presentationResult.body, (item) => item.source_key || item.dataset_id)[0];
    const presentation = group?.items[0]?.presentation;
    if (!routeEpoch.isCurrent()) return;
    view.replaceChildren();
    append(view, pageHeading(
      "Publishing settings",
      presentedName(presentation, product.display_name || product.dataset_id),
      `${presentation?.purpose ? `${presentation.purpose} · ` : ""}${researchAreaLabel(product.target_feature)} · ${product.product_schema_version}`,
    ));
    const accepted = product.latest_accepted_release;
    append(view, panel(
      "Publication configuration",
      "How this dataset is prepared and shared",
      detailList([
        ["Dataset", displayName(product.dataset_id)],
        ["Catalogue group", group?.label || "Other datasets"],
        ["Update / import profile", `${product.job_profile} / ${product.import_profile}`],
        ["Publishing process", `${product.builder_key} ${product.builder_version}`],
        ["Schema", product.product_schema_version],
        ["Ordering", product.ordering_rule],
        ["Acquisition scope", "Complete registered source"],
        ["Redistribution", `${product.redistribution_decision} (${product.download_permitted ? "download permitted" : "download restricted"})`],
        ["Configured support", badge(product.capability_state)],
        ["Published version", accepted ? technicalDetails(accepted, "Inspect published version") : "No published version yet"],
        ["Known limitations", product.known_limitations.join(" ")],
      ]),
    ));
  }

  return { renderDataProducts };
}
