import {
  prepareMiragePixelBuffers,
  prepareMirageSources,
  processPreparedMiragePixels,
} from "./mirage.js";

const bridge = window.AstrBotPluginView;
const PAGE_SIZE = 30;

const els = {
  notice: document.querySelector("#notice"),
  openTaskCenter: document.querySelector("#openTaskCenterButton"),
  refreshButton: document.querySelector("#refreshButton"),
  openMirage: document.querySelector("#openMirageButton"),
  mirageModal: document.querySelector("#mirageModal"),
  closeMirage: document.querySelector("#closeMirageButton"),
  useSelectedMirage: document.querySelector("#useSelectedMirageButton"),
  swapMirage: document.querySelector("#swapMirageImagesButton"),
  mirageInnerPickerCategory: document.querySelector("#mirageInnerPickerCategory"),
  mirageInnerPickerGrid: document.querySelector("#mirageInnerPickerGrid"),
  mirageInnerPickerPrevious: document.querySelector("#mirageInnerPickerPrevious"),
  mirageInnerPickerNext: document.querySelector("#mirageInnerPickerNext"),
  mirageInnerPickerPage: document.querySelector("#mirageInnerPickerPage"),
  mirageCoverPickerCategory: document.querySelector("#mirageCoverPickerCategory"),
  mirageCoverPickerGrid: document.querySelector("#mirageCoverPickerGrid"),
  mirageCoverPickerPrevious: document.querySelector("#mirageCoverPickerPrevious"),
  mirageCoverPickerNext: document.querySelector("#mirageCoverPickerNext"),
  mirageCoverPickerPage: document.querySelector("#mirageCoverPickerPage"),
  mirageSettingsStatus: document.querySelector("#mirageSettingsStatus"),
  mirageInnerId: document.querySelector("#mirageInnerIdInput"),
  mirageCoverId: document.querySelector("#mirageCoverIdInput"),
  loadMirageSources: document.querySelector("#loadMirageSourcesButton"),
  mirageInnerPreview: document.querySelector("#mirageInnerPreview"),
  mirageCoverPreview: document.querySelector("#mirageCoverPreview"),
  mirageInnerMeta: document.querySelector("#mirageInnerMeta"),
  mirageCoverMeta: document.querySelector("#mirageCoverMeta"),
  mirageStatus: document.querySelector("#mirageStatus"),
  mirageMaxSize: document.querySelector("#mirageMaxSizeInput"),
  mirageInnerScale: document.querySelector("#mirageInnerScaleInput"),
  mirageCoverScale: document.querySelector("#mirageCoverScaleInput"),
  mirageInnerDesat: document.querySelector("#mirageInnerDesatInput"),
  mirageCoverDesat: document.querySelector("#mirageCoverDesatInput"),
  mirageWeight: document.querySelector("#mirageWeightInput"),
  mirageColored: document.querySelector("#mirageColoredInput"),
  mirageMaxSizeValue: document.querySelector("#mirageMaxSizeValue"),
  mirageInnerScaleValue: document.querySelector("#mirageInnerScaleValue"),
  mirageCoverScaleValue: document.querySelector("#mirageCoverScaleValue"),
  mirageInnerDesatValue: document.querySelector("#mirageInnerDesatValue"),
  mirageCoverDesatValue: document.querySelector("#mirageCoverDesatValue"),
  mirageWeightValue: document.querySelector("#mirageWeightValue"),
  mirageWhiteCanvas: document.querySelector("#mirageWhiteCanvas"),
  mirageBlackCanvas: document.querySelector("#mirageBlackCanvas"),
  mirageRawCanvas: document.querySelector("#mirageRawCanvas"),
  mirageOutputMeta: document.querySelector("#mirageOutputMeta"),
  mirageCategory: document.querySelector("#mirageCategorySelect"),
  mirageSave: document.querySelector("#saveMirageButton"),
  mirageSizeHint: document.querySelector("#mirageSizeHint"),
  taskCenterBadge: document.querySelector("#taskCenterBadge"),
  taskCenterModal: document.querySelector("#taskCenterModal"),
  closeTaskCenter: document.querySelector("#closeTaskCenterButton"),
  refreshTasks: document.querySelector("#refreshTasksButton"),
  taskStaleSummary: document.querySelector("#taskStaleSummary"),
  reassessSfw: document.querySelector("#reassessSfwButton"),
  reassessNsfw: document.querySelector("#reassessNsfwButton"),
  taskNsfwProvider: document.querySelector("#taskNsfwProviderSelect"),
  taskListSummary: document.querySelector("#taskListSummary"),
  taskList: document.querySelector("#taskList"),
  taskEmptyState: document.querySelector("#taskEmptyState"),
  categorySelect: document.querySelector("#categorySelect"),
  galleryTitle: document.querySelector("#galleryTitle"),
  gallerySummary: document.querySelector("#gallerySummary"),
  grid: document.querySelector("#imageGrid"),
  emptyState: document.querySelector("#emptyState"),
  galleryPanel: document.querySelector("#galleryPanel"),
  duplicatePanel: document.querySelector("#duplicatePanel"),
  duplicateCheck: document.querySelector("#duplicateCheckButton"),
  duplicateBack: document.querySelector("#duplicateBackButton"),
  duplicateThreshold: document.querySelector("#duplicateThresholdSelect"),
  startDuplicateScan: document.querySelector("#startDuplicateScanButton"),
  duplicateScanStatus: document.querySelector("#duplicateScanStatus"),
  duplicateProgress: document.querySelector("#duplicateProgress"),
  duplicateProgressFill: document.querySelector("#duplicateProgressFill"),
  duplicateProgressLabel: document.querySelector("#duplicateProgressLabel"),
  exactDuplicatesTab: document.querySelector("#exactDuplicatesTab"),
  similarImagesTab: document.querySelector("#similarImagesTab"),
  exactDuplicatesCount: document.querySelector("#exactDuplicatesCount"),
  similarImagesCount: document.querySelector("#similarImagesCount"),
  duplicateSelectAll: document.querySelector("#duplicateSelectAllButton"),
  duplicateInvertSelection: document.querySelector("#duplicateInvertSelectionButton"),
  duplicateClearSelection: document.querySelector("#duplicateClearSelectionButton"),
  duplicateSelectedCount: document.querySelector("#duplicateSelectedCount"),
  duplicateTrash: document.querySelector("#duplicateTrashButton"),
  duplicateResults: document.querySelector("#duplicateResults"),
  duplicateEmptyState: document.querySelector("#duplicateEmptyState"),
  duplicatePagination: document.querySelector("#duplicatePagination"),
  duplicatePageSummary: document.querySelector("#duplicatePageSummary"),
  duplicatePreviousPage: document.querySelector("#duplicatePreviousPageButton"),
  duplicateNextPage: document.querySelector("#duplicateNextPageButton"),
  pageSummary: document.querySelector("#pageSummary"),
  selectedCount: document.querySelector("#selectedCount"),
  selectAll: document.querySelector("#selectAllButton"),
  invertSelection: document.querySelector("#invertSelectionButton"),
  clearSelection: document.querySelector("#clearSelectionButton"),
  deleteImages: document.querySelector("#deleteImagesButton"),
  activeToolbar: document.querySelector("#activeToolbar"),
  activeSearchPanel: document.querySelector("#activeSearchPanel"),
  activeSelectionActions: document.querySelector("#activeSelectionActions"),
  openTrash: document.querySelector("#openTrashButton"),
  trashActions: document.querySelector("#trashActions"),
  trashBack: document.querySelector("#trashBackButton"),
  trashSelectAll: document.querySelector("#trashSelectAllButton"),
  trashInvertSelection: document.querySelector("#trashInvertSelectionButton"),
  trashClearSelection: document.querySelector("#trashClearSelectionButton"),
  trashSelectedCount: document.querySelector("#trashSelectedCount"),
  restoreTrashSelected: document.querySelector("#restoreTrashSelectedButton"),
  purgeTrashSelected: document.querySelector("#purgeTrashSelectedButton"),
  emptyTrash: document.querySelector("#emptyTrashButton"),
  editTags: document.querySelector("#editTagsButton"),
  evaluateSfwSelected: document.querySelector("#evaluateSfwSelectedButton"),
  moveImages: document.querySelector("#moveImagesButton"),
  moveTarget: document.querySelector("#moveTargetSelect"),
  deleteCategory: document.querySelector("#deleteCategoryButton"),
  previousPage: document.querySelector("#previousPageButton"),
  nextPage: document.querySelector("#nextPageButton"),
  fileInput: document.querySelector("#fileInput"),
  uploadButton: document.querySelector("#uploadButton"),
  tagTaxonomyButton: document.querySelector("#tagTaxonomyButton"),
  tagTaxonomyPanel: document.querySelector("#tagTaxonomyPanel"),
  tagTaxonomyBack: document.querySelector("#tagTaxonomyBackButton"),
  tagAliasForm: document.querySelector("#tagAliasForm"),
  tagAliasInput: document.querySelector("#tagAliasInput"),
  tagCanonicalInput: document.querySelector("#tagCanonicalInput"),
  tagAliasList: document.querySelector("#tagAliasList"),
  tagHierarchyForm: document.querySelector("#tagHierarchyForm"),
  tagChildInput: document.querySelector("#tagChildInput"),
  tagParentInput: document.querySelector("#tagParentInput"),
  tagHierarchyList: document.querySelector("#tagHierarchyList"),
  tagSuggestionList: document.querySelector("#tagSuggestionList"),
  previewTagNormalization: document.querySelector("#previewTagNormalizationButton"),
  tagNormalizationPreview: document.querySelector("#tagNormalizationPreview"),
  tagNormalizationSummary: document.querySelector("#tagNormalizationSummary"),
  tagNormalizationAliases: document.querySelector("#tagNormalizationAliases"),
  applyTagNormalization: document.querySelector("#applyTagNormalizationButton"),
  useCanonicalBulkTag: document.querySelector("#useCanonicalBulkTagButton"),
  bulkTagAliasHint: document.querySelector("#bulkTagAliasHint"),
  useCanonicalDetailTag: document.querySelector("#useCanonicalDetailTagButton"),
  categoryModal: document.querySelector("#categoryModal"),
  categoryForm: document.querySelector("#categoryForm"),
  categoryName: document.querySelector("#categoryNameInput"),
  categoryNsfw: document.querySelector("#categoryNsfwInput"),
  confirmModal: document.querySelector("#confirmModal"),
  confirmTitle: document.querySelector("#confirmTitle"),
  confirmMessage: document.querySelector("#confirmMessage"),
  confirmAccept: document.querySelector("#acceptConfirmButton"),
  semanticQuery: document.querySelector("#semanticQueryInput"),
  semanticSearch: document.querySelector("#semanticSearchButton"),
  clearSearch: document.querySelector("#clearSearchButton"),
  rebuildSfwIndex: document.querySelector("#rebuildSfwIndexButton"),
  rebuildNsfwIndex: document.querySelector("#rebuildNsfwIndexButton"),
  reindexStatus: document.querySelector("#reindexStatus"),
  nsfwEvaluationRow: document.querySelector("#nsfwEvaluationRow"),
  nsfwProvider: document.querySelector("#nsfwProviderSelect"),
  evaluateSelected: document.querySelector("#evaluateSelectedButton"),
  activeTagFilter: document.querySelector("#activeTagFilter"),
  activeTagFilterLabel: document.querySelector("#activeTagFilterLabel"),
  clearTagFilter: document.querySelector("#clearTagFilterButton"),
  tagsModal: document.querySelector("#tagsModal"),
  tagsForm: document.querySelector("#tagsForm"),
  tagsModalTitle: document.querySelector("#tagsModalTitle"),
  tagMode: document.querySelector("#tagModeSelect"),
  tagsInput: document.querySelector("#tagsInput"),
  aiProviderSummary: document.querySelector("#aiProviderSummary"),
  detailModal: document.querySelector("#detailModal"),
  detailForm: document.querySelector("#detailForm"),
  detailTitle: document.querySelector("#detailTitle"),
  detailPreview: document.querySelector("#detailPreview"),
  detailAiTags: document.querySelector("#detailAiTags"),
  clearAiEvaluation: document.querySelector("#clearAiEvaluationButton"),
  clearAiEvaluationHint: document.querySelector("#clearAiEvaluationHint"),
  detailDescription: document.querySelector("#detailDescriptionInput"),
  detailManualTagInput: document.querySelector("#detailManualTagInput"),
  addDetailManualTag: document.querySelector("#addDetailManualTagButton"),
  detailManualTagsList: document.querySelector("#detailManualTagsList"),
  detailManualTagsHint: document.querySelector("#detailManualTagsHint"),
};

const state = {
  categories: [],
  categoryId: "",
  targetCategoryId: "",
  page: 1,
  pages: 1,
  total: 0,
  selected: new Set(),
  visibleItems: new Map(),
  tagFilter: "",
  searchActive: false,
  searchQuery: "",
  tagTargetIds: [],
  tagAliases: [],
  tagHierarchy: [],
  tagSuggestions: [],
  tagNormalizationPlan: null,
  detailItemId: null,
  detailCategoryId: "",
  clearAiEvaluation: false,
  detailAiTags: [],
  detailManualTags: [],
  trashMode: false,
  tagProviders: [],
  sfwProviderId: "",
  nsfwProviderId: "",
  noticeTimer: 0,
  embeddingBusy: false,
  duplicateMode: false,
  duplicateKind: "exact",
  duplicatePage: 1,
  duplicatePages: 1,
  duplicateTotal: 0,
  duplicateSelected: new Set(),
  duplicateJob: null,
  taskCenterOpen: false,
  taskCenterSeenFailedIds: new Set(),
  mirageSources: { inner: null, cover: null },
  miragePreparedKey: "",
  miragePreparedPixels: null,
  mirageFallbackPrepared: null,
  mirageWorker: null,
  mirageWorkerPreparedKey: "",
  mirageWorkerRequestId: 0,
  mirageWorkerPending: new Map(),
  mirageRenderRequestId: 0,
  mirageOutputReady: false,
  mirageOutputNsfw: false,
  mirageMaxImageBytes: 0,
  mirageRenderTimer: 0,
  miragePicker: {
    inner: { categoryId: "", page: 1, pages: 1, items: [], requestId: 0 },
    cover: { categoryId: "", page: 1, pages: 1, items: [], requestId: 0 },
  },
  mirageSelectedIds: { inner: 0, cover: 0 },
  mirageSourceCache: new Map(),
  mirageSourceRequestId: 0,
  mirageSettingsLoaded: false,
  mirageSettingsSaveTimer: 0,
  mirageSettingsSaveChain: Promise.resolve(),
  taskPollTimer: 0,
  taskData: null,
  taskStatusSnapshot: new Map(),
};

function showNotice(message, kind = "success", duration = 5000) {
  window.clearTimeout(state.noticeTimer);
  els.notice.textContent = message;
  els.notice.className = `notice ${kind}`;
  els.notice.hidden = false;
  if (duration > 0) {
    state.noticeTimer = window.setTimeout(() => { els.notice.hidden = true; }, duration);
  }
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** index;
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value || "未知")
    : date.toLocaleString("zh-CN", { hour12: false });
}

function selectedCategory() {
  return state.categories.find((category) => category.id === state.categoryId) || null;
}

function renderMoveTargets() {
  const previousId = state.targetCategoryId;
  const targets = state.categories.filter((category) => category.id !== state.categoryId);
  els.moveTarget.replaceChildren();
  for (const category of targets) {
    const option = document.createElement("option");
    option.value = category.id;
    option.textContent = `${category.name}${category.is_nsfw ? " · NSFW" : ""}`;
    els.moveTarget.append(option);
  }
  state.targetCategoryId = targets.some((category) => category.id === previousId)
    ? previousId
    : (targets[0]?.id || "");
  els.moveTarget.value = state.targetCategoryId;
  els.moveTarget.disabled = targets.length === 0;
  els.moveImages.disabled = state.selected.size === 0 || targets.length === 0;
}

async function loadCategories(preferredId = state.categoryId) {
  state.categories = await bridge.apiGet("categories");
  if (!Array.isArray(state.categories)) state.categories = [];
  state.categoryId = state.categories.some((category) => category.id === preferredId)
    ? preferredId
    : (state.categories[0]?.id || "");

  els.categorySelect.replaceChildren();
  for (const category of state.categories) {
    const option = document.createElement("option");
    option.value = category.id;
    option.textContent = `${category.name}${category.is_nsfw ? " · NSFW" : ""} (${category.image_count} 项)`;
    els.categorySelect.append(option);
  }
  els.categorySelect.value = state.categoryId;
  const category = selectedCategory();
  els.deleteCategory.disabled = !category || category.id === "pending";
  renderMoveTargets();
  await loadImages();
}

function clearTagNormalizationPreview() {
  state.tagNormalizationPlan = null;
  els.tagNormalizationPreview.hidden = true;
  els.applyTagNormalization.disabled = true;
  els.tagNormalizationAliases.replaceChildren();
}

function renderTagTaxonomy() {
  els.tagAliasList.replaceChildren();
  if (!state.tagAliases.length) {
    const empty = document.createElement("p");
    empty.className = "hint taxonomy-empty";
    empty.textContent = "还没有设置标签别名。";
    els.tagAliasList.append(empty);
  }
  for (const entry of state.tagAliases) {
    const row = document.createElement("div");
    row.className = "taxonomy-list-row";
    const label = document.createElement("span");
    label.textContent = entry.alias + " → " + entry.canonical_tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "button secondary danger-text";
    remove.textContent = "删除";
    remove.dataset.alias = entry.alias;
    remove.setAttribute("aria-label", "删除别名 " + entry.alias);
    row.append(label, remove);
    els.tagAliasList.append(row);
  }

  els.tagHierarchyList.replaceChildren();
  if (!state.tagHierarchy.length) {
    const empty = document.createElement("p");
    empty.className = "hint taxonomy-empty";
    empty.textContent = "还没有设置标签层级。";
    els.tagHierarchyList.append(empty);
  }
  for (const entry of state.tagHierarchy) {
    const row = document.createElement("div");
    row.className = "taxonomy-list-row";
    const label = document.createElement("span");
    label.textContent = entry.child_tag + " → 父标签：" + entry.parent_tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "button secondary danger-text";
    remove.textContent = "删除";
    remove.dataset.childTag = entry.child_tag;
    remove.setAttribute("aria-label", "删除子标签 " + entry.child_tag + " 的层级");
    row.append(label, remove);
    els.tagHierarchyList.append(row);
  }
}

async function loadTagTaxonomy() {
  const data = await bridge.apiGet("tags/taxonomy");
  state.tagAliases = Array.isArray(data.aliases) ? data.aliases : [];
  state.tagHierarchy = Array.isArray(data.hierarchy) ? data.hierarchy : [];
  state.tagSuggestions = Array.isArray(data.suggestions) ? data.suggestions : [];
  renderTagTaxonomy();
  els.tagSuggestionList.replaceChildren();
  const suggestionTags = new Map();
  for (const entry of state.tagSuggestions) {
    suggestionTags.set(entry.tag, Number(entry.usage_count) || 0);
  }
  for (const entry of state.tagAliases) {
    suggestionTags.set(entry.alias, suggestionTags.get(entry.alias) || 0);
    suggestionTags.set(entry.canonical_tag, suggestionTags.get(entry.canonical_tag) || 0);
  }
  for (const entry of state.tagHierarchy) {
    suggestionTags.set(entry.child_tag, suggestionTags.get(entry.child_tag) || 0);
    suggestionTags.set(entry.parent_tag, suggestionTags.get(entry.parent_tag) || 0);
  }
  for (const [tag, count] of suggestionTags) {
    const option = document.createElement("option");
    option.value = tag;
    if (count) option.label = "已使用 " + count + " 次";
    els.tagSuggestionList.append(option);
  }
}

function exactTagAlias(value) {
  const key = String(value || "").trim().toLocaleLowerCase();
  return state.tagAliases.find((entry) => entry.alias.toLocaleLowerCase() === key) || null;
}

function renderAliasHint(value, hint, button) {
  const entry = exactTagAlias(value);
  if (!entry) {
    hint.textContent = "";
    button.hidden = true;
    button.dataset.canonicalTag = "";
    return;
  }
  hint.textContent = "“" + entry.alias + "”是“" + entry.canonical_tag
    + "”的别名。保存时仍保留你输入的标签；只有点击右侧按钮才会改用规范标签。";
  button.textContent = "改用“" + entry.canonical_tag + "”";
  button.dataset.canonicalTag = entry.canonical_tag;
  button.hidden = false;
}

function updateDetailTagAliasHint() {
  renderAliasHint(
    els.detailManualTagInput.value,
    els.detailManualTagsHint,
    els.useCanonicalDetailTag,
  );
  if (!els.detailManualTagInput.value.trim()) {
    els.detailManualTagsHint.textContent = "按 Enter 或点击“添加”保存标签；每个标签最多 32 个字符，每个媒体最多保留 30 个手工标签。AI 标签与手工标签分开保存。";
  }
}

function updateBulkTagAliasHint() {
  const raw = els.tagsInput.value;
  const splitAt = Math.max(raw.lastIndexOf(","), raw.lastIndexOf("，"), raw.lastIndexOf("、"));
  const last = raw.slice(splitAt + 1).trim();
  renderAliasHint(last, els.bulkTagAliasHint, els.useCanonicalBulkTag);
}

function renderTagNormalizationPreview(plan) {
  state.tagNormalizationPlan = plan;
  els.tagNormalizationPreview.hidden = false;
  const invalidated = Number(plan.invalidated_embeddings) || 0;
  els.tagNormalizationSummary.textContent = "确认后将规范化 " + plan.updated_tags
    + " 个标签，影响 " + plan.updated_media + " 个媒体；其中 AI 标签变化会使 "
    + invalidated + " 个语义索引失效。";
  els.tagNormalizationAliases.replaceChildren();
  const affected = (plan.by_alias || []).filter((entry) => entry.occurrences > 0);
  if (!affected.length) {
    const empty = document.createElement("p");
    empty.className = "hint taxonomy-empty";
    empty.textContent = "当前没有与别名完全匹配的存量标签。";
    els.tagNormalizationAliases.append(empty);
  }
  for (const entry of affected) {
    const row = document.createElement("div");
    row.className = "taxonomy-list-row";
    const label = document.createElement("span");
    label.textContent = entry.alias + " → " + entry.canonical_tag + "（" + entry.occurrences + " 项）";
    row.append(label);
    els.tagNormalizationAliases.append(row);
  }
  els.applyTagNormalization.disabled = !plan.updated_tags;
}

async function openTagTaxonomyPanel() {
  els.activeToolbar.hidden = true;
  els.activeSearchPanel.hidden = true;
  els.galleryPanel.hidden = true;
  els.duplicatePanel.hidden = true;
  els.tagTaxonomyPanel.hidden = false;
  clearTagNormalizationPreview();
  try {
    await loadTagTaxonomy();
  } catch (error) {
    showNotice(error.message || "读取标签体系失败。", "error", 0);
  }
}

function updateSelectionControls() {
  const checkboxes = [...els.grid.querySelectorAll("input[data-image-id]")];
  if (state.trashMode) {
    const hasSelection = state.selected.size > 0;
    els.trashSelectedCount.textContent = `已选 ${state.selected.size} 项`;
    els.trashSelectAll.disabled = checkboxes.length === 0;
    els.trashInvertSelection.disabled = checkboxes.length === 0;
    els.trashClearSelection.disabled = !hasSelection;
    els.restoreTrashSelected.disabled = !hasSelection;
    els.purgeTrashSelected.disabled = !hasSelection;
    els.emptyTrash.disabled = state.total === 0;
    return;
  }
  els.selectedCount.textContent = `已选 ${state.selected.size} 项`;
  els.deleteImages.disabled = state.selected.size === 0;
  els.editTags.disabled = state.selected.size < 2;
  els.moveImages.disabled = state.selected.size === 0 || !state.targetCategoryId;
  els.selectAll.disabled = checkboxes.length === 0;
  els.invertSelection.disabled = checkboxes.length === 0;
  els.clearSelection.disabled = state.selected.size === 0;
  const selectedItems = [...state.selected].map((id) => state.visibleItems.get(id)).filter(Boolean);
  const allSelectedNsfw = selectedItems.length === state.selected.size
    && selectedItems.length > 0
    && selectedItems.every((item) => item.is_nsfw);
  const allSelectedSfw = selectedItems.length === state.selected.size
    && selectedItems.length > 0
    && selectedItems.every((item) => !item.is_nsfw);
  els.nsfwEvaluationRow.hidden = !allSelectedNsfw;
  els.evaluateSelected.disabled = !allSelectedNsfw || !els.nsfwProvider.value;
  els.evaluateSfwSelected.disabled = !allSelectedSfw || !state.sfwProviderId;
}

function changeVisibleSelection(mode) {
  const checkboxes = [...els.grid.querySelectorAll("input[data-image-id]")];
  if (mode === "clear") state.selected.clear();
  for (const checkbox of checkboxes) {
    const id = Number(checkbox.dataset.imageId);
    const selected = mode === "all"
      ? true
      : mode === "invert"
        ? !checkbox.checked
        : false;
    checkbox.checked = selected;
    if (selected) state.selected.add(id);
    else state.selected.delete(id);
    checkbox.closest(".image-card").classList.toggle("selected", selected);
  }
  updateSelectionControls();
}

function updateDuplicateSelectionControls() {
  const checkboxes = [...els.duplicateResults.querySelectorAll("input[data-duplicate-id]")];
  const hasSelection = state.duplicateSelected.size > 0;
  els.duplicateSelectedCount.textContent = "已选 " + state.duplicateSelected.size + " 项";
  els.duplicateSelectAll.disabled = checkboxes.length === 0;
  els.duplicateInvertSelection.disabled = checkboxes.length === 0;
  els.duplicateClearSelection.disabled = !hasSelection;
  els.duplicateTrash.disabled = !hasSelection || state.duplicateSelected.size > 500;
  els.duplicateTrash.title = state.duplicateSelected.size > 500
    ? "每次最多移入回收站 500 项，请减少选择"
    : "";
}

function syncDuplicateMediaSelection(id) {
  const selected = state.duplicateSelected.has(id);
  for (const checkbox of els.duplicateResults.querySelectorAll("input[data-duplicate-id]")) {
    if (Number(checkbox.dataset.duplicateId) !== id) continue;
    checkbox.checked = selected;
    checkbox.closest(".duplicate-media-card").classList.toggle("selected", selected);
  }
}

function makeDuplicateMediaCard(item) {
  const card = document.createElement("article");
  card.className = "duplicate-media-card";
  const checkboxLabel = document.createElement("label");
  checkboxLabel.className = "duplicate-media-check";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.dataset.duplicateId = String(item.id);
  checkbox.checked = state.duplicateSelected.has(item.id);
  checkbox.addEventListener("change", () => {
    if (checkbox.checked && !state.duplicateSelected.has(item.id)
      && state.duplicateSelected.size >= 500) {
      checkbox.checked = false;
      showNotice("每次最多选择 500 个媒体移入回收站。", "error");
      return;
    }
    if (checkbox.checked) state.duplicateSelected.add(item.id);
    else state.duplicateSelected.delete(item.id);
    syncDuplicateMediaSelection(item.id);
    updateDuplicateSelectionControls();
  });
  checkboxLabel.append(checkbox);

  const preview = document.createElement("div");
  preview.className = "duplicate-media-preview";
  if (item.thumbnail) {
    const image = document.createElement("img");
    image.src = item.thumbnail;
    image.alt = "媒体 " + item.id + " 预览";
    image.loading = "lazy";
    preview.append(image);
  } else {
    const placeholder = document.createElement("span");
    placeholder.className = "duplicate-no-preview";
    placeholder.textContent = item.media_type === "video" ? "视频无预览" : "图片无预览";
    preview.append(placeholder);
  }

  const info = document.createElement("div");
  info.className = "duplicate-media-info";
  const title = document.createElement("strong");
  title.textContent = "媒体 #" + item.id + " · " + (item.category_name || "未知分类");
  const metadata = document.createElement("span");
  const dimensions = item.width && item.height ? item.width + " × " + item.height : "尺寸未知";
  metadata.textContent = (item.media_type === "video" ? "视频" : "图片")
    + " · " + dimensions + " · " + formatBytes(item.size_bytes);
  info.append(title, metadata);
  if (item.is_nsfw) {
    const badge = document.createElement("span");
    badge.className = "duplicate-nsfw-badge";
    badge.textContent = "NSFW";
    info.append(badge);
  }
  card.append(checkboxLabel, preview, info);
  if (checkbox.checked) card.classList.add("selected");
  return card;
}

function makeDuplicateGroup(entry) {
  const group = document.createElement("article");
  group.className = "duplicate-group";
  const heading = document.createElement("div");
  heading.className = "duplicate-group-heading";
  const title = document.createElement("strong");
  if (state.duplicateKind === "exact") {
    title.textContent = "完全相同 · " + entry.media.length + " 项";
  } else {
    title.textContent = "相似图片 · 感知距离 " + entry.distance + "/64";
  }
  const detail = document.createElement("span");
  detail.className = "hint";
  detail.textContent = state.duplicateKind === "exact"
    ? "SHA-256 " + String(entry.sha256 || "").slice(0, 16) + "…"
    : "阈值 " + (state.duplicateJob?.threshold ?? els.duplicateThreshold.value) + "；距离越小越相似";
  heading.append(title, detail);
  const media = document.createElement("div");
  media.className = "duplicate-media-row";
  for (const item of entry.media) media.append(makeDuplicateMediaCard(item));
  group.append(heading, media);
  return group;
}

function renderDuplicateJob(job) {
  state.duplicateJob = job;
  const running = job?.status === "running";
  els.startDuplicateScan.disabled = running;
  els.startDuplicateScan.textContent = running ? "扫描中…" : "开始扫描";
  els.duplicateProgress.hidden = !running;
  if (running) {
    els.duplicateEmptyState.hidden = true;
    const total = Number(job.total) || 0;
    const processed = Number(job.processed) || 0;
    const percent = total > 0 ? Math.min(100, processed / total * 100) : 0;
    els.duplicateProgressFill.style.width = String(percent) + "%";
    const phaseLabel = job.phase === "hashing" ? "补算历史图片感知哈希"
      : job.phase === "comparing" ? "比较不同分类中的图片"
        : "准备扫描";
    els.duplicateProgressLabel.textContent = total > 0
      ? phaseLabel + "：" + processed + " / " + total
      : phaseLabel + "…";
    els.duplicateScanStatus.textContent = "扫描过程中可以离开此页；重新打开后会继续显示进度。";
    return;
  }
  if (job?.status === "completed") {
    els.exactDuplicatesCount.textContent = (job.exact_groups || 0) + " 组";
    els.similarImagesCount.textContent = (job.similar_pairs || 0) + " 对";
    const errors = Number(job.hash_errors) || 0;
    const truncated = job.truncated ? "；相似候选已达到 3000 对上限" : "";
    els.duplicateScanStatus.textContent = "检查完成：" + (job.exact_groups || 0)
      + " 组完全重复，" + (job.similar_pairs || 0) + " 对相似图片"
      + (errors ? "；" + errors + " 张图片无法计算感知哈希" : "") + truncated;
  } else if (job?.status === "failed") {
    els.duplicateScanStatus.textContent = "扫描失败：" + (job.error || "未知错误");
  } else if (job?.status === "idle") {
    els.duplicateScanStatus.textContent = "尚未扫描";
    els.duplicateEmptyState.querySelector("strong").textContent = "尚未开始扫描";
    els.duplicateEmptyState.querySelector("span").textContent = "选择相似度阈值后点击“开始扫描”。";
    els.duplicateEmptyState.hidden = false;
  } else if (job?.status === "cancelled") {
    els.duplicateScanStatus.textContent = "扫描已取消，请重新开始。";
    els.duplicateEmptyState.hidden = true;
  } else {
    els.duplicateEmptyState.hidden = true;
  }
}

function updateDuplicateTabs() {
  const exactActive = state.duplicateKind === "exact";
  els.exactDuplicatesTab.classList.toggle("active", exactActive);
  els.similarImagesTab.classList.toggle("active", !exactActive);
  els.exactDuplicatesTab.setAttribute("aria-selected", String(exactActive));
  els.similarImagesTab.setAttribute("aria-selected", String(!exactActive));
}

async function loadDuplicateResults() {
  if (state.duplicateJob?.status !== "completed") return;
  const data = await bridge.apiGet("duplicates/results", {
    kind: state.duplicateKind,
    page: state.duplicatePage,
    page_size: 10,
  });
  state.duplicatePage = data.page;
  state.duplicatePages = data.pages;
  state.duplicateTotal = data.total;
  els.duplicateResults.replaceChildren();
  for (const item of data.items) {
    els.duplicateResults.append(makeDuplicateGroup(item));
  }
  els.duplicateEmptyState.hidden = data.items.length > 0;
  els.duplicatePagination.hidden = data.total === 0;
  els.duplicatePageSummary.textContent = "第 " + data.page + " / " + data.pages + " 页 · 共 "
    + data.total + (state.duplicateKind === "exact" ? " 组" : " 对");
  els.duplicatePreviousPage.disabled = data.page <= 1;
  els.duplicateNextPage.disabled = data.page >= data.pages;
  updateDuplicateTabs();
  updateDuplicateSelectionControls();
}

async function pollDuplicateScan() {
  while (state.duplicateMode) {
    const job = await bridge.apiGet("duplicates/status");
    renderDuplicateJob(job);
    if (job.status !== "running") {
      if (job.status === "completed") {
        state.duplicatePage = 1;
        await loadDuplicateResults();
        if (job.truncated) {
          showNotice("扫描完成，但相似候选达到 3000 对上限。可降低阈值后重新扫描。", "error", 8000);
        }
      }
      return;
    }
    await delay(1000);
  }
}

async function openDuplicatePanel() {
  state.duplicateMode = true;
  els.activeToolbar.hidden = true;
  els.activeSearchPanel.hidden = true;
  els.galleryPanel.hidden = true;
  els.duplicatePanel.hidden = false;
  els.duplicateResults.replaceChildren();
  els.duplicateEmptyState.hidden = true;
  els.duplicatePagination.hidden = true;
  try {
    const job = await bridge.apiGet("duplicates/status");
    renderDuplicateJob(job);
    if (job.status === "completed") {
      els.exactDuplicatesCount.textContent = (job.exact_groups || 0) + " 组";
      els.similarImagesCount.textContent = (job.similar_pairs || 0) + " 对";
      await loadDuplicateResults();
    } else if (job.status === "running") {
      await pollDuplicateScan();
    }
  } catch (error) {
    showNotice(error.message || "读取重复项检查状态失败。", "error", 0);
  }
}

async function startDuplicateScan() {
  const threshold = Number(els.duplicateThreshold.value);
  state.duplicateSelected.clear();
  state.duplicatePage = 1;
  els.exactDuplicatesCount.textContent = "…";
  els.similarImagesCount.textContent = "…";
  els.duplicateResults.replaceChildren();
  els.duplicateEmptyState.hidden = true;
  els.duplicatePagination.hidden = true;
  updateDuplicateSelectionControls();
  try {
    const job = await bridge.apiPost("duplicates/scan", { threshold });
    renderDuplicateJob(job);
    await pollDuplicateScan();
  } catch (error) {
    showNotice(error.message || "启动重复项检查失败。", "error", 0);
    renderDuplicateJob({ status: "failed", error: error.message });
  }
}

function changeDuplicateSelection(mode) {
  const checkboxes = [...els.duplicateResults.querySelectorAll("input[data-duplicate-id]")];
  const ids = [...new Set(checkboxes.map((checkbox) => Number(checkbox.dataset.duplicateId)))];
  let skipped = 0;
  if (mode === "clear") state.duplicateSelected.clear();
  for (const id of ids) {
    const selected = mode === "all" ? true
      : mode === "invert" ? !state.duplicateSelected.has(id)
        : false;
    if (selected && !state.duplicateSelected.has(id) && state.duplicateSelected.size >= 500) {
      skipped += 1;
      continue;
    }
    if (selected) state.duplicateSelected.add(id);
    else state.duplicateSelected.delete(id);
    syncDuplicateMediaSelection(id);
  }
  updateDuplicateSelectionControls();
  if (skipped) showNotice("已达到单次 500 项上限，部分媒体未选中。", "error");
}

async function trashDuplicateSelection() {
  const ids = [...state.duplicateSelected];
  if (!ids.length || ids.length > 500) return;
  const accepted = await confirmAction(
    "将所选媒体移入回收站？",
    "所选 " + ids.length + " 个媒体可从回收站还原。请确保每组完全重复项至少保留一份；相似图片也可能是误报。移入后会重新扫描当前媒体库。",
    "移入回收站",
  );
  if (!accepted) return;
  try {
    const result = await bridge.apiPost("images/delete", { image_ids: ids });
    state.duplicateSelected.clear();
    showNotice("已将 " + result.trashed + " 个媒体移入回收站，正在重新扫描。");
    await startDuplicateScan();
  } catch (error) {
    showNotice(error.message || "移入回收站失败。", "error", 0);
  }
}

async function loadAiProviders() {
  const data = await bridge.apiGet("ai/providers");
  state.tagProviders = Array.isArray(data.chat) ? data.chat : [];
  state.sfwProviderId = data.sfw_provider_id || "";
  els.nsfwProvider.replaceChildren();
  if (!state.tagProviders.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "没有可用的聊天模型";
    els.nsfwProvider.append(option);
  } else {
    for (const provider of state.tagProviders) {
      const option = document.createElement("option");
      option.value = provider.id;
      option.textContent = `${provider.name} · ${provider.id}`;
      els.nsfwProvider.append(option);
    }
    const configuredNsfwId = data.nsfw_provider_id || "";
    els.nsfwProvider.value = state.tagProviders.some((provider) => provider.id === configuredNsfwId)
      ? configuredNsfwId
      : state.tagProviders[0].id;
  }
  state.nsfwProviderId = els.nsfwProvider.value || "";
  const sfwProvider = state.tagProviders.find((provider) => provider.id === data.sfw_provider_id);
  const nsfwProvider = state.tagProviders.find((provider) => provider.id === data.nsfw_provider_id);
  const embeddingProvider = (data.embedding || []).find((provider) => provider.id === data.embedding_provider_id);
  const sfwLabel = sfwProvider ? `${sfwProvider.name} (${sfwProvider.id})` : (data.sfw_provider_id || "未配置");
  const nsfwLabel = nsfwProvider
    ? `${nsfwProvider.name} (${nsfwProvider.id})`
    : (data.nsfw_provider_id ? `${data.nsfw_provider_id}（当前不可用）` : "未配置");
  const embeddingLabel = embeddingProvider ? `${embeddingProvider.name} (${embeddingProvider.id})` : (data.embedding_provider_id || "未配置");
  els.aiProviderSummary.textContent = `SFW 自动评估模型：${sfwLabel}；NSFW 人工评估默认模型：${nsfwLabel}；Embedding 模型：${embeddingLabel}。模型可在插件配置页修改，NSFW 评估时也可临时改选。`;
  updateSelectionControls();
}

const taskTypeLabels = {
  compression: "媒体压缩",
  video_preview: "视频预览图",
  ai_evaluation: "AI 评估",
  semantic_index: "语义索引",
};
const taskStatusLabels = {
  queued: "排队中",
  running: "处理中",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
  skipped: "已跳过",
};

function updateTaskNsfwProviderOptions(configuredId = "") {
  const currentId = els.taskNsfwProvider.value;
  const currentOptions = [...els.taskNsfwProvider.options].map((option) => option.value);
  const providerIds = state.tagProviders.map((provider) => provider.id);
  if (!providerIds.length) {
    if (currentOptions.length !== 1 || currentOptions[0] !== "") {
      els.taskNsfwProvider.replaceChildren();
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "没有可用的聊天模型";
      els.taskNsfwProvider.append(option);
    }
    return;
  }
  if (currentOptions.join("\u0000") === providerIds.join("\u0000")) {
    if (currentId && providerIds.includes(currentId)) return;
    const fallback = providerIds.includes(configuredId) ? configuredId : providerIds[0];
    if (fallback) els.taskNsfwProvider.value = fallback;
    return;
  }
  els.taskNsfwProvider.replaceChildren();
  if (!state.tagProviders.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "没有可用的聊天模型";
    els.taskNsfwProvider.append(option);
    return;
  }
  for (const provider of state.tagProviders) {
    const option = document.createElement("option");
    option.value = provider.id;
    option.textContent = `${provider.name} · ${provider.id}`;
    els.taskNsfwProvider.append(option);
  }
  const preferred = [currentId, configuredId].find((id) =>
    state.tagProviders.some((provider) => provider.id === id)
  );
  els.taskNsfwProvider.value = preferred || state.tagProviders[0].id;
}

function taskDateLabel(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function makeTaskCard(task) {
  const card = document.createElement("article");
  card.className = `processing-task-card task-${task.status}`;

  const top = document.createElement("div");
  top.className = "processing-task-top";
  const title = document.createElement("strong");
  title.textContent = taskTypeLabels[task.task_type] || task.task_type;
  const status = document.createElement("span");
  status.className = `task-status task-status-${task.status}`;
  status.textContent = (taskStatusLabels[task.status] || task.status) + (task.status === "failed" && task.has_retry ? "（已有后续重试）" : "");
  top.append(title, status);

  const subject = document.createElement("p");
  subject.className = "processing-task-subject";
  const metadata = task.metadata || {};
  subject.textContent = task.media_id
    ? `媒体 #${task.media_id}${task.scope ? ` · ${task.scope.toUpperCase()}` : ""}`
    : (metadata.file_name || "入库媒体");

  const message = document.createElement("p");
  message.className = "processing-task-message";
  message.textContent = task.message || "等待处理";

  const progress = document.createElement("div");
  progress.className = "processing-task-progress";
  const track = document.createElement("div");
  track.className = "processing-task-progress-track";
  const fill = document.createElement("span");
  const percent = Math.max(0, Math.min(100, Number(task.progress) || 0));
  fill.style.width = `${percent}%`;
  track.append(fill);
  const progressText = document.createElement("span");
  progressText.className = "hint";
  progressText.textContent = `${percent}%`;
  progress.append(track, progressText);

  const details = document.createElement("div");
  details.className = "processing-task-details";
  const detailParts = [`创建于 ${taskDateLabel(task.created_at)}`];
  if (task.model_id) detailParts.push(`模型：${task.model_id}`);
  if (task.prompt_version) detailParts.push(`提示词版本：${task.prompt_version}`);
  if (task.completed_at) detailParts.push(`结束于 ${taskDateLabel(task.completed_at)}`);
  details.textContent = detailParts.join(" · ");

  card.append(top, subject, message, progress, details);
  if (task.error) {
    const error = document.createElement("p");
    error.className = "processing-task-error";
    error.textContent = `原因：${task.error}`;
    card.append(error);
  }
  const actions = document.createElement("div");
  actions.className = "processing-task-actions";
  if (task.can_retry) {
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "button secondary";
    retry.textContent = "重试";
    retry.addEventListener("click", () => operateProcessingTask(task, "retry", retry));
    actions.append(retry);
  }
  if (task.can_cancel) {
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "button secondary danger-text";
    cancel.textContent = "取消";
    cancel.addEventListener("click", () => operateProcessingTask(task, "cancel", cancel));
    actions.append(cancel);
  }
  if (actions.childElementCount) card.append(actions);
  return card;
}

async function operateProcessingTask(task, action, button) {
  button.disabled = true;
  try {
    await bridge.apiPost("tasks/action", { task_id: task.task_id, action });
    showNotice(action === "retry" ? "已提交任务重试。" : "已请求取消任务。", "success", 3500);
    await loadTaskCenter();
  } catch (error) {
    showNotice(error.message || "任务操作失败。", "error", 0);
    button.disabled = false;
  }
}

async function loadTaskCenter() {
  const nsfwProviderId = els.taskNsfwProvider.value || state.nsfwProviderId || "";
  const data = await bridge.apiGet("tasks", { nsfw_provider_id: nsfwProviderId });
  state.taskData = data;
  const tasks = Array.isArray(data.tasks) ? data.tasks : [];
  let videoPreviewCompleted = false;
  const nextSnapshot = new Map();
  for (const task of tasks) {
    nextSnapshot.set(task.task_id, task.status);
    if (
      task.task_type === "video_preview"
      && task.status === "succeeded"
      && state.taskStatusSnapshot.get(task.task_id) !== "succeeded"
    ) videoPreviewCompleted = true;
  }
  state.taskStatusSnapshot = nextSnapshot;
  const stale = data.stale || {};
  updateTaskNsfwProviderOptions(stale.nsfw_model_id || "");
  els.taskStaleSummary.textContent =
    `SFW：${stale.sfw_model_id ? `${stale.sfw || 0} 项过期 · 模型 ${stale.sfw_model_id} · 提示词 ${stale.sfw_prompt_version}` : "未配置评估模型"}；`
    + `NSFW：${stale.nsfw_model_id ? `${stale.nsfw || 0} 项过期 · 当前模型 ${stale.nsfw_model_id} · 提示词 ${stale.nsfw_prompt_version}` : "请选择评估模型"}。`;
  els.reassessSfw.disabled = !stale.sfw || !stale.sfw_model_id;
  els.reassessNsfw.disabled = !stale.nsfw || !state.tagProviders.length;

  const visibleTaskIds = new Set(tasks.map((task) => task.task_id));
  for (const taskId of state.taskCenterSeenFailedIds) {
    if (!visibleTaskIds.has(taskId)) state.taskCenterSeenFailedIds.delete(taskId);
  }
  const failedTasks = tasks.filter(
    (task) => task.status === "failed" && !task.has_retry,
  );
  const unseenFailedIds = new Set(
    failedTasks
      .filter((task) => !state.taskCenterSeenFailedIds.has(task.task_id))
      .map((task) => task.task_id),
  );
  const activeCount = tasks.filter((task) => ["queued", "running"].includes(task.status)).length;
  const unreadFailedCount = state.taskCenterOpen ? 0 : unseenFailedIds.size;
  const attentionCount = activeCount + unreadFailedCount;
  els.taskCenterBadge.hidden = attentionCount === 0;
  els.taskCenterBadge.textContent = attentionCount > 99 ? "99+" : String(attentionCount);

  const taskPriority = (task) => {
    if (["queued", "running"].includes(task.status)) return 0;
    if (unseenFailedIds.has(task.task_id)) return 1;
    return 2;
  };
  const taskDate = (task) => new Date(task.created_at || "").getTime() || 0;
  const displayTasks = [...tasks].sort((left, right) =>
    taskPriority(left) - taskPriority(right)
      || taskDate(right) - taskDate(left)
      || String(right.task_id).localeCompare(String(left.task_id))
  );
  const counts = tasks.reduce((total, task) => {
    total[task.status] = (total[task.status] || 0) + 1;
    return total;
  }, {});
  els.taskListSummary.textContent =
    `最近显示 ${tasks.length} 项 · 排队 ${counts.queued || 0} · 处理中 ${counts.running || 0} · 失败 ${counts.failed || 0} · 成功 ${counts.succeeded || 0}`;
  els.taskList.replaceChildren();
  els.taskEmptyState.hidden = tasks.length > 0;
  for (const task of displayTasks) els.taskList.append(makeTaskCard(task));
  if (state.taskCenterOpen) {
    for (const taskId of unseenFailedIds) state.taskCenterSeenFailedIds.add(taskId);
  }
  if (videoPreviewCompleted && !els.galleryPanel.hidden && !state.searchActive && !state.trashMode) {
    loadImages().catch(() => {});
  }
}

function openTaskCenter() {
  state.taskCenterOpen = true;
  els.taskCenterModal.hidden = false;
  loadTaskCenter().catch((error) => {
    els.taskListSummary.textContent = error.message || "读取任务失败。";
    showNotice(error.message || "读取任务失败。", "error", 0);
  });
  window.clearInterval(state.taskPollTimer);
  state.taskPollTimer = window.setInterval(() => {
    loadTaskCenter().catch((error) => {
      els.taskListSummary.textContent = error.message || "刷新任务失败。";
    });
  }, 3000);
}

function closeTaskCenter() {
  state.taskCenterOpen = false;
  els.taskCenterModal.hidden = true;
  window.clearInterval(state.taskPollTimer);
  state.taskPollTimer = 0;
}

async function reassessStaleMedia(scope) {
  const stale = state.taskData?.stale || {};
  const total = Number(stale[scope]) || 0;
  if (!total) return;
  const providerId = scope === "sfw"
    ? stale.sfw_model_id
    : els.taskNsfwProvider.value;
  if (!providerId) {
    showNotice("请先选择可用的视觉评估模型。", "error");
    return;
  }
  const accepted = await confirmAction(
    `重评过期 ${scope.toUpperCase()} 媒体？`,
    `将使用模型“${providerId}”和当前提示词，重新生成 ${total} 项媒体的 AI 描述与标签，并覆盖旧 AI 结果。${scope === "nsfw" ? "本操作会把所选 NSFW 媒体或视频抽帧发送给该模型。" : ""}`,
    "开始重评",
  );
  if (!accepted) return;
  const button = scope === "sfw" ? els.reassessSfw : els.reassessNsfw;
  button.disabled = true;
  try {
    const result = await bridge.apiPost("tasks/reassess", { scope, provider_id: providerId });
    showNotice(
      `已提交 ${result.scheduled} 项过期媒体的重新评估；${result.skipped_active} 项已有任务正在运行。`,
      "success",
      6000,
    );
    await loadTaskCenter();
  } catch (error) {
    showNotice(error.message || "提交过期媒体重评失败。", "error", 0);
    button.disabled = false;
  }
}

function openTagsModal(imageIds) {
  state.tagTargetIds = [...new Set(imageIds.map(Number))];
  if (state.tagTargetIds.length < 2) {
    state.tagTargetIds = [];
    return;
  }
  els.tagsModalTitle.textContent = `批量维护 ${state.tagTargetIds.length} 个媒体的标签`;
  els.tagMode.value = "add";
  els.tagsInput.value = "";
  updateBulkTagAliasHint();
  els.tagsModal.hidden = false;
  els.tagsInput.focus();
}

function closeTagsModal() {
  els.tagsModal.hidden = true;
  state.tagTargetIds = [];
}

function renderEditableTagChips(container, tags, source, onRemove, emptyLabel) {
  container.replaceChildren();
  if (!tags.length) {
    const none = document.createElement("span");
    none.className = "hint";
    none.textContent = emptyLabel;
    container.append(none);
    return;
  }
  tags.forEach((tag, index) => {
    const chip = document.createElement("span");
    chip.className = `tag-chip ${source} detail-editable-tag`;
    const text = document.createElement("span");
    text.textContent = tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "tag-remove-button";
    remove.textContent = "×";
    remove.title = `移除${source === "ai" ? "AI" : "手工"}标签：${tag}`;
    remove.setAttribute("aria-label", `移除${source === "ai" ? "AI" : "手工"}标签 ${tag}`);
    remove.addEventListener("click", () => onRemove(index));
    chip.append(text, remove);
    container.append(chip);
  });
}

function renderDetailAiTags() {
  renderEditableTagChips(
    els.detailAiTags,
    state.detailAiTags,
    "ai",
    (index) => {
      state.detailAiTags.splice(index, 1);
      renderDetailAiTags();
    },
    "暂无 AI 标签",
  );
}

function renderDetailManualTags() {
  renderEditableTagChips(
    els.detailManualTagsList,
    state.detailManualTags,
    "manual",
    (index) => {
      state.detailManualTags.splice(index, 1);
      renderDetailManualTags();
    },
    "暂无手工标签",
  );
}

function addDetailManualTag() {
  const tag = els.detailManualTagInput.value.trim().replace(/\s+/g, " ");
  if (!tag) {
    els.detailManualTagInput.focus();
    return;
  }
  if (Array.from(tag).length > 32) {
    els.detailManualTagsHint.textContent = "单个标签不能超过 32 个字符。";
    return;
  }
  if (state.detailManualTags.length >= 30) {
    els.detailManualTagsHint.textContent = "每个媒体最多保留 30 个手工标签。";
    return;
  }
  if (state.detailManualTags.some((value) => value.toLocaleLowerCase() === tag.toLocaleLowerCase())) {
    els.detailManualTagsHint.textContent = "这个手工标签已经添加。";
    return;
  }
  state.detailManualTags.push(tag);
  els.detailManualTagInput.value = "";
  updateDetailTagAliasHint();
  renderDetailManualTags();
  els.detailManualTagInput.focus();
}

function openDetailModal(item) {
  state.detailItemId = item.id;
  state.detailCategoryId = item.category_id || "";
  state.clearAiEvaluation = false;
  state.detailAiTags = [...(item.ai_tags || [])];
  state.detailManualTags = [...(item.manual_tags || [])];
  const mediaLabel = item.media_type === "video" ? "视频" : "图片";
  const categoryName = item.category_name
    || state.categories.find((category) => category.id === item.category_id)?.name
    || "图集";
  els.detailTitle.textContent = `${categoryName} · ${mediaLabel} ${item.id}`;
  els.detailPreview.replaceChildren();
  if (item.thumbnail) {
    const preview = document.createElement("img");
    preview.src = item.thumbnail;
    preview.alt = `${mediaLabel}预览 ${item.id}`;
    els.detailPreview.append(preview);
  } else {
    const empty = document.createElement("span");
    empty.className = "hint";
    empty.textContent = "暂无预览图";
    els.detailPreview.append(empty);
  }
  renderDetailAiTags();
  renderDetailManualTags();
  els.detailDescription.value = item.description || item.ai_description || "";
  els.clearAiEvaluation.disabled = !(
    String(item.ai_description || "").trim()
    || String(item.description_override || "").trim()
    || (item.ai_tags || []).length
  );
  els.clearAiEvaluationHint.textContent = "点击后会清空 AI 描述、AI 标签和手动描述覆盖；手工标签保留。点击“保存详情”后生效。";
  els.detailManualTagInput.value = "";
  updateDetailTagAliasHint();
  els.detailModal.hidden = false;
  els.detailDescription.focus();
}

function closeDetailModal() {
  els.detailModal.hidden = true;
  state.detailItemId = null;
  state.detailCategoryId = "";
  state.clearAiEvaluation = false;
  state.detailAiTags = [];
  state.detailManualTags = [];
  els.detailManualTagInput.value = "";
}

function makeImageCard(item, isTrash = false) {
  state.visibleItems.set(item.id, item);
  const card = document.createElement("article");
  card.className = `image-card${state.selected.has(item.id) ? " selected" : ""}`;

  const checkboxLabel = document.createElement("label");
  checkboxLabel.className = "card-checkbox";
  checkboxLabel.title = `选择媒体 ${item.id}`;
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.dataset.imageId = String(item.id);
  checkbox.checked = state.selected.has(item.id);
  checkbox.setAttribute("aria-label", `选择媒体 ${item.id}`);
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) state.selected.add(item.id);
    else state.selected.delete(item.id);
    card.classList.toggle("selected", checkbox.checked);
    updateSelectionControls();
  });
  checkboxLabel.append(checkbox);

  const preview = document.createElement("div");
  preview.className = "image-thumb";
  if (item.media_type === "video") {
    const videoPreview = document.createElement("div");
    videoPreview.className = item.thumbnail
      ? "video-preview has-thumbnail"
      : "video-preview";
    if (item.thumbnail) {
      const thumbnail = document.createElement("img");
      thumbnail.src = item.thumbnail;
      thumbnail.alt = `视频预览 ${item.id}`;
      thumbnail.loading = "lazy";
      videoPreview.append(thumbnail);
    } else {
      const play = document.createElement("span");
      play.className = "video-play-icon";
      play.textContent = "▶";
      videoPreview.append(play);
    }
    const label = document.createElement("span");
    label.className = "video-preview-label";
    label.textContent = item.thumbnail ? `视频 · ${item.image_format}` : "暂无预览";
    videoPreview.append(label);
    preview.append(videoPreview);
  } else {
    const image = document.createElement("img");
    image.src = item.thumbnail;
    image.alt = `图集图片 ${item.id}`;
    image.loading = "lazy";
    preview.append(image);
  }
  if (!isTrash) {
    preview.classList.add("clickable-preview");
    preview.title = "点击查看描述和标签详情";
    preview.addEventListener("click", () => openDetailModal(item));
  }

  const info = document.createElement("div");
  info.className = "image-info";
  const idLine = document.createElement("div");
  idLine.className = "image-id";
  const id = document.createElement("span");
  id.textContent = `编号 ${item.id}`;
  const format = document.createElement("span");
  format.className = "format-pill";
  format.textContent = item.media_type === "video" ? `视频 · ${item.image_format}` : item.image_format;
  idLine.append(id, format);
  if (item.is_nsfw) {
    const nsfw = document.createElement("span");
    nsfw.className = "format-pill nsfw-pill";
    nsfw.textContent = "NSFW";
    idLine.append(nsfw);
  }
  const meta = document.createElement("div");
  meta.className = "image-meta";
  const categoryName = item.category_name
    || state.categories.find((category) => category.id === item.category_id)?.name;
  meta.textContent = isTrash
    ? `原分类「${categoryName || "未知"}」 · 删除于 ${formatDate(item.trashed_at)} · ${formatBytes(item.size_bytes)}`
    : item.media_type === "video"
      ? `${categoryName ? `「${categoryName}」 · ` : ""}${formatBytes(item.size_bytes)}`
      : `${categoryName ? `「${categoryName}」 · ` : ""}${item.width} × ${item.height} · ${formatBytes(item.size_bytes)}`;
  info.append(idLine, meta);

  const effectiveDescription = item.description || item.ai_description || "";
  if (effectiveDescription) {
    const description = document.createElement("div");
    description.className = "ai-description";
    description.textContent = effectiveDescription;
    info.append(description);
  }

  const tagList = document.createElement("div");
  tagList.className = "tag-list";
  for (const [tag, source] of [
    ...(item.manual_tags || []).map((value) => [value, "manual"]),
    ...(item.ai_tags || []).map((value) => [value, "ai"]),
  ]) {
    const chip = document.createElement(isTrash ? "span" : "button");
    if (!isTrash) {
      chip.type = "button";
      chip.className = `tag-chip filterable ${source}`;
      chip.title = "点击按此标签筛选当前分类";
      chip.addEventListener("click", () => {
        state.searchActive = false;
        state.tagFilter = tag;
        state.categoryId = item.category_id;
        state.page = 1;
        loadCategories(item.category_id).catch((error) => showNotice(error.message, "error", 0));
      });
    } else {
      chip.className = `tag-chip ${source}`;
    }
    chip.textContent = source === "ai" ? `${tag} · AI` : tag;
    tagList.append(chip);
  }
  if (tagList.childElementCount) info.append(tagList);

  const statusLabels = {
    not_evaluated: "尚未评估",
    pending: "SFW 自动评估等待中",
    processing: "AI 正在评估…",
    evaluated: "AI 描述已生成",
    failed: "AI 评估失败，可重试",
    manual_required: "NSFW 需后台手动评估",
  };
  const aiStatus = document.createElement("div");
  aiStatus.className = `ai-status${item.ai_status === "failed" ? " failed" : ""}`;
  const statusLabel = item.description_override
    ? `描述已手动编辑${item.embedding_ready ? "" : " · 语义索引未建立"}`
    : (item.ai_status === "evaluated" && !item.embedding_ready
      ? "AI 描述已生成 · 语义索引未建立"
      : (statusLabels[item.ai_status] || ""));
  aiStatus.textContent = item.ai_error
    ? `${statusLabel || "AI 状态"}：${item.ai_error}`
    : statusLabel;
  if (aiStatus.textContent) info.append(aiStatus);

  const cardActions = document.createElement("div");
  cardActions.className = "card-actions";
  if (isTrash) {
    const restore = document.createElement("button");
    restore.type = "button";
    restore.className = "button secondary";
    restore.textContent = "还原";
    restore.addEventListener("click", () => restoreTrash([item.id]));
    const purge = document.createElement("button");
    purge.type = "button";
    purge.className = "button danger";
    purge.textContent = "彻底删除";
    purge.addEventListener("click", () => permanentlyDeleteTrash([item.id]));
    cardActions.append(restore, purge);
  } else {
    const details = document.createElement("button");
    details.type = "button";
    details.className = "button secondary";
    details.textContent = "详情";
    details.addEventListener("click", () => openDetailModal(item));
    cardActions.append(details);
  }
  if (!isTrash && Number.isFinite(item.score)) {
    const score = document.createElement("span");
    score.className = "similarity-score";
    score.textContent = `相似度 ${Math.round(item.score * 100)}%`;
    cardActions.append(score);
  }
  info.append(cardActions);
  card.append(checkboxLabel, preview, info);
  return card;
}

async function loadImages() {
  state.selected.clear();
  state.visibleItems.clear();
  els.grid.replaceChildren();
  if (state.trashMode) {
    els.activeToolbar.hidden = true;
    els.activeSearchPanel.hidden = true;
    els.activeSelectionActions.hidden = true;
    els.trashActions.hidden = false;
    els.activeTagFilter.hidden = true;
    return loadTrash();
  }
  els.activeToolbar.hidden = false;
  els.activeSearchPanel.hidden = false;
  els.activeSelectionActions.hidden = false;
  els.trashActions.hidden = true;
  els.activeTagFilter.hidden = !state.tagFilter;
  els.activeTagFilterLabel.textContent = state.tagFilter ? `标签筛选：${state.tagFilter}` : "";
  if (state.searchActive) return loadSearchResults();
  els.clearSearch.hidden = true;
  document.querySelector(".pagination").hidden = false;
  if (!state.categoryId) {
    els.galleryTitle.textContent = "媒体";
    els.gallerySummary.textContent = "暂无分类";
    els.emptyState.querySelector("strong").textContent = "暂无分类";
    els.emptyState.querySelector("span").textContent = "可以从聊天收藏或批量导入媒体。";
    els.emptyState.hidden = false;
    updateSelectionControls();
    return;
  }

  const data = await bridge.apiGet("images", {
    category_id: state.categoryId,
    page: state.page,
    page_size: PAGE_SIZE,
    tag: state.tagFilter,
  });
  if (state.page > data.pages) {
    state.page = data.pages;
    return loadImages();
  }
  const category = data.category;
  state.pages = data.pages;
  state.total = data.total;
  els.galleryTitle.textContent = category.name;
  els.gallerySummary.textContent = `${category.image_count} 个媒体${category.is_nsfw ? " · NSFW 分类" : ""}`;
  els.pageSummary.textContent = `第 ${data.page} / ${data.pages} 页 · 共 ${data.total} 项`;
  els.previousPage.disabled = data.page <= 1;
  els.nextPage.disabled = data.page >= data.pages;
  els.emptyState.querySelector("strong").textContent = "这个分类还没有媒体";
  els.emptyState.querySelector("span").textContent = "可以从聊天指令收藏图片或视频，或在这里批量导入。";
  els.emptyState.hidden = data.items.length > 0;
  for (const item of data.items) els.grid.append(makeImageCard(item));
  updateSelectionControls();
}

async function loadTrash() {
  document.querySelector(".pagination").hidden = false;
  const data = await bridge.apiGet("trash", {
    page: state.page,
    page_size: PAGE_SIZE,
  });
  if (state.page > data.pages) {
    state.page = data.pages;
    return loadTrash();
  }
  state.pages = data.pages;
  state.total = data.total;
  els.galleryTitle.textContent = "回收站";
  els.gallerySummary.textContent = `${data.total} 个媒体 · 服务器本地时间每日 0 点自动清空`;
  els.pageSummary.textContent = `第 ${data.page} / ${data.pages} 页 · 共 ${data.total} 项`;
  els.previousPage.disabled = data.page <= 1;
  els.nextPage.disabled = data.page >= data.pages;
  els.emptyState.querySelector("strong").textContent = "回收站为空";
  els.emptyState.querySelector("span").textContent = "移入回收站的图片和视频会在每日 0 点自动清空。";
  els.emptyState.hidden = data.items.length > 0;
  for (const item of data.items) els.grid.append(makeImageCard(item, true));
  updateSelectionControls();
}

async function loadSearchResults() {
  const query = state.searchQuery.trim();
  if (!query) return;
  els.clearSearch.hidden = false;
  els.activeTagFilter.hidden = true;
  document.querySelector(".pagination").hidden = true;
  const data = await bridge.apiPost("ai/search", {
    query,
  });
  els.galleryTitle.textContent = "语义检索结果";
  els.gallerySummary.textContent = `“${query}” · 显示最多 30 个最相似媒体，共 ${data.items.length} 项`;
  els.pageSummary.textContent = "语义检索结果";
  els.previousPage.disabled = true;
  els.nextPage.disabled = true;
  els.emptyState.hidden = data.items.length > 0;
  if (!data.items.length) {
    els.emptyState.querySelector("strong").textContent = "没有匹配的已索引媒体";
    els.emptyState.querySelector("span").textContent = "请确认已配置 Embedding 模型，并为媒体建立了语义索引。";
  }
  for (const item of data.items) els.grid.append(makeImageCard(item));
  updateSelectionControls();
}

async function runSemanticSearch() {
  state.searchQuery = els.semanticQuery.value.trim();
  if (!state.searchQuery) {
    showNotice("请输入要查找的画面描述。", "error");
    return;
  }
  state.searchActive = true;
  els.semanticSearch.disabled = true;
  try {
    await loadImages();
    showNotice("语义检索完成。", "success", 3000);
  } catch (error) {
    showNotice(error.message || "语义检索失败。", "error", 0);
  } finally {
    els.semanticSearch.disabled = false;
  }
}

async function rebuildEmbeddingIndex(scope) {
  if (state.embeddingBusy) return;
  const scopeLabel = scope.toUpperCase();
  const buttons = [els.rebuildSfwIndex, els.rebuildNsfwIndex];
  state.embeddingBusy = true;
  buttons.forEach((button) => { button.disabled = true; });
  els.reindexStatus.textContent = "正在统计可重建媒体…";
  try {
    const preview = await bridge.apiPost("ai/reindex", { scope });
    if (!preview.total) {
      els.reindexStatus.textContent = `${scopeLabel} 没有可建立索引的描述或 AI 标签。`;
      showNotice(`${scopeLabel} 没有可重建的语义索引。`, "success", 5000);
      return;
    }
    const accepted = await confirmAction(
      `重建 ${scopeLabel} 语义索引？`,
      `将使用“${preview.provider_id}”重新生成 ${preview.total} 个媒体的向量，并覆盖这些媒体的旧向量。描述和 AI 标签文本会发送到该 Embedding 服务。`,
      "开始重建",
    );
    if (!accepted) {
      els.reindexStatus.textContent = "已取消。";
      return;
    }
    const job = await bridge.apiPost("ai/reindex", {
      scope,
      confirm: true,
      expected_total: preview.total,
    });
    if (job.status === "completed" && job.total === 0) {
      els.reindexStatus.textContent = "没有可重建媒体。";
      return;
    }
    els.reindexStatus.textContent = `正在重建 ${scopeLabel} 索引：0 / ${job.total}`;
    let latest = job;
    while (latest.status === "running") {
      await new Promise((resolve) => window.setTimeout(resolve, 900));
      latest = await bridge.apiGet("ai/reindex/status");
      if (latest.job_id !== job.job_id) {
        throw new Error("索引任务状态已变化，请刷新页面查看。");
      }
      els.reindexStatus.textContent = `正在重建 ${scopeLabel} 索引：${latest.processed} / ${latest.total}（成功 ${latest.indexed}，失败 ${latest.failed}，取消 ${latest.cancelled || 0}）`;
    }
    if (latest.status === "completed") {
      els.reindexStatus.textContent = `重建完成：成功 ${latest.indexed}，失败 ${latest.failed}，取消 ${latest.cancelled || 0}。`;
      showNotice(`${scopeLabel} 索引重建完成：成功 ${latest.indexed}，失败 ${latest.failed}，取消 ${latest.cancelled || 0}。`, latest.failed || latest.cancelled ? "error" : "success", 0);
      await loadImages();
    } else {
      els.reindexStatus.textContent = `索引重建${latest.status === "cancelled" ? "已中断" : "失败"}：已处理 ${latest.processed} / ${latest.total}。`;
      showNotice(els.reindexStatus.textContent, "error", 0);
    }
  } catch (error) {
    els.reindexStatus.textContent = error.message || "索引重建失败。";
    showNotice(els.reindexStatus.textContent, "error", 0);
  } finally {
    state.embeddingBusy = false;
    buttons.forEach((button) => { button.disabled = false; });
  }
}

async function refresh() {
  try {
    await loadCategories();
    await loadTagTaxonomy();
  } catch (error) {
    showNotice(error.message || "读取图集失败。", "error", 0);
  }
}

async function restoreTrash(imageIds) {
  try {
    const result = await bridge.apiPost("trash/restore", { image_ids: imageIds });
    await loadImages();
    showNotice(
      `还原完成：${result.restored} 个已恢复，${result.skipped_duplicates} 个与现有媒体重复，仍保留在回收站。`,
      "success",
      7000,
    );
  } catch (error) {
    showNotice(error.message || "还原媒体失败。", "error", 0);
  }
}

async function permanentlyDeleteTrash(imageIds) {
  if (!imageIds.length) return;
  const accepted = await confirmAction(
    "彻底删除回收站媒体？",
    `将永久删除 ${imageIds.length} 个媒体文件，无法还原。`,
    "彻底删除",
  );
  if (!accepted) return;
  try {
    const result = await bridge.apiPost("trash/delete", { image_ids: imageIds });
    await loadImages();
    showNotice(`已永久删除 ${result.deleted} 个媒体。`);
  } catch (error) {
    showNotice(error.message || "彻底删除失败。", "error", 0);
  }
}

async function emptyTrash() {
  if (!state.total) return;
  const accepted = await confirmAction(
    "清空回收站？",
    `将永久删除回收站中的 ${state.total} 个媒体文件，无法还原。`,
    "清空回收站",
  );
  if (!accepted) return;
  try {
    const result = await bridge.apiPost("trash/empty", {});
    await loadImages();
    showNotice(`回收站已清空，永久删除 ${result.deleted} 个媒体。`);
  } catch (error) {
    showNotice(error.message || "清空回收站失败。", "error", 0);
  }
}

function openCategoryModal() {
  els.categoryForm.reset();
  els.categoryModal.hidden = false;
  els.categoryName.focus();
}

function closeCategoryModal() {
  els.categoryModal.hidden = true;
}

function confirmAction(title, message, actionLabel = "确认删除") {
  els.confirmTitle.textContent = title;
  els.confirmMessage.textContent = message;
  els.confirmAccept.textContent = actionLabel;
  els.confirmModal.hidden = false;
  return new Promise((resolve) => {
    const finish = (accepted) => {
      els.confirmModal.hidden = true;
      els.confirmAccept.removeEventListener("click", accept);
      document.querySelector("#cancelConfirmButton").removeEventListener("click", cancel);
      resolve(accepted);
    };
    const accept = () => finish(true);
    const cancel = () => finish(false);
    els.confirmAccept.addEventListener("click", accept, { once: true });
    document.querySelector("#cancelConfirmButton").addEventListener("click", cancel, { once: true });
  });
}

function setMirageStatus(message, isError = false) {
  els.mirageStatus.textContent = message;
  els.mirageStatus.classList.toggle("error", isError);
}

function mirageOptions() {
  return {
    maxSize: Number(els.mirageMaxSize.value),
    scaleInner: Number(els.mirageInnerScale.value),
    scaleCover: Number(els.mirageCoverScale.value),
    desatInner: Number(els.mirageInnerDesat.value),
    desatCover: Number(els.mirageCoverDesat.value),
    weightInner: Number(els.mirageWeight.value),
    colored: els.mirageColored.checked,
  };
}

function updateMirageControlLabels() {
  els.mirageMaxSizeValue.textContent = Number(els.mirageMaxSize.value) + " px";
  els.mirageInnerScaleValue.textContent = Number(els.mirageInnerScale.value).toFixed(2);
  els.mirageCoverScaleValue.textContent = Number(els.mirageCoverScale.value).toFixed(2);
  els.mirageInnerDesatValue.textContent = Number(els.mirageInnerDesat.value).toFixed(2);
  els.mirageCoverDesatValue.textContent = Number(els.mirageCoverDesat.value).toFixed(2);
  els.mirageWeightValue.textContent = Number(els.mirageWeight.value).toFixed(2);
}

function renderMirageCategories() {
  const previousId = els.mirageCategory.value;
  const sourcesAreNsfw = Boolean(
    state.mirageSources.inner?.is_nsfw || state.mirageSources.cover?.is_nsfw,
  );
  const categories = state.categories.filter((category) => !sourcesAreNsfw || category.is_nsfw);
  els.mirageCategory.replaceChildren();
  for (const category of categories) {
    const option = document.createElement("option");
    option.value = category.id;
    option.textContent = category.name + (category.is_nsfw ? " · NSFW" : "");
    els.mirageCategory.append(option);
  }

  const preferred = categories.find((category) => category.id === previousId)
    || categories.find((category) => category.id === state.categoryId)
    || categories.find((category) => category.id === "pending")
    || categories[0];
  els.mirageCategory.value = preferred?.id || "";
  els.mirageCategory.disabled = categories.length === 0;
  if (sourcesAreNsfw && categories.length === 0) {
    setMirageStatus("来源含 NSFW 媒体，但当前没有可保存的 NSFW 分类。请先创建或恢复一个 NSFW 分类。", true);
  }
  els.mirageSave.disabled = !state.mirageOutputReady || !preferred;
}

function ensureMirageWorker() {
  if (state.mirageWorker) return state.mirageWorker;
  if (typeof Worker === "undefined") return null;
  try {
    const worker = new Worker(new URL("./mirage-worker.js", import.meta.url), {
      type: "module",
    });
    worker.addEventListener("message", (event) => {
      const response = event.data || {};
      const pending = state.mirageWorkerPending.get(response.requestId);
      if (!pending) return;
      state.mirageWorkerPending.delete(response.requestId);
      if (response.ok) pending.resolve(response);
      else pending.reject(new Error(response.error || "预览计算失败。"));
    });
    worker.addEventListener("error", (event) => {
      const error = new Error(event.message || "浏览器后台像素处理不可用。");
      if (state.mirageWorker === worker) {
        state.mirageWorker = null;
        state.mirageWorkerPreparedKey = "";
      }
      for (const pending of state.mirageWorkerPending.values()) {
        pending.reject(error);
      }
      state.mirageWorkerPending.clear();
    });
    state.mirageWorker = worker;
    return worker;
  } catch (_error) {
    return null;
  }
}

function requestMirageWorker(type, payload, transfer = []) {
  const worker = ensureMirageWorker();
  if (!worker) return Promise.reject(new Error("浏览器后台像素处理不可用。"));
  const requestId = ++state.mirageWorkerRequestId;
  return new Promise((resolve, reject) => {
    state.mirageWorkerPending.set(requestId, { resolve, reject });
    try {
      worker.postMessage({ requestId, type, ...payload }, transfer);
    } catch (error) {
      state.mirageWorkerPending.delete(requestId);
      reject(error);
    }
  });
}

function stopMirageWorker(error) {
  const worker = state.mirageWorker;
  state.mirageWorker = null;
  state.mirageWorkerPreparedKey = "";
  if (worker) worker.terminate();
  for (const pending of state.mirageWorkerPending.values()) {
    pending.reject(error);
  }
  state.mirageWorkerPending.clear();
}

async function renderMiragePixels(inner, cover, options) {
  const previewSize = Number(els.mirageMaxSize.value) || 1200;
  const sourceKey = String(inner.id) + ":" + String(cover.id) + ":" + String(previewSize);
  if (state.miragePreparedKey !== sourceKey || !state.miragePreparedPixels) {
    state.miragePreparedPixels = prepareMirageSources(
      inner.image,
      cover.image,
      previewSize,
    );
    state.mirageFallbackPrepared = null;
    state.miragePreparedKey = sourceKey;
    state.mirageWorkerPreparedKey = "";
  }

  const worker = ensureMirageWorker();
  if (worker) {
    try {
      if (state.mirageWorkerPreparedKey !== sourceKey) {
        const innerBuffer = state.miragePreparedPixels.innerData.slice().buffer;
        const coverBuffer = state.miragePreparedPixels.coverData.slice().buffer;
        await requestMirageWorker(
          "prepare",
          {
            width: state.miragePreparedPixels.width,
            height: state.miragePreparedPixels.height,
            innerBuffer,
            coverBuffer,
          },
          [innerBuffer, coverBuffer],
        );
        state.mirageWorkerPreparedKey = sourceKey;
      }
      const result = await requestMirageWorker("render", { options });
      return new ImageData(
        new Uint8ClampedArray(result.pixelBuffer),
        result.width,
        result.height,
      );
    } catch (error) {
      stopMirageWorker(error);
    }
  }
  if (!state.mirageFallbackPrepared) {
    state.mirageFallbackPrepared = prepareMiragePixelBuffers(
      state.miragePreparedPixels.width,
      state.miragePreparedPixels.height,
      state.miragePreparedPixels.innerData,
      state.miragePreparedPixels.coverData,
    );
  }
  return processPreparedMiragePixels(state.mirageFallbackPrepared, options);
}

function clearMirageOutput() {
  state.mirageRenderRequestId += 1;
  state.mirageOutputReady = false;
  state.mirageOutputNsfw = false;
  state.miragePreparedKey = "";
  state.miragePreparedPixels = null;
  state.mirageFallbackPrepared = null;
  state.mirageWorkerPreparedKey = "";
  for (const canvas of [els.mirageWhiteCanvas, els.mirageBlackCanvas, els.mirageRawCanvas]) {
    canvas.width = 0;
    canvas.height = 0;
  }
  els.mirageOutputMeta.textContent = "载入图片后生成预览";
  els.mirageSave.disabled = true;
}

async function renderMirageOutput() {
  const inner = state.mirageSources.inner;
  const cover = state.mirageSources.cover;
  if (!inner || !cover) {
    clearMirageOutput();
    return;
  }

  const requestId = ++state.mirageRenderRequestId;
  try {
    const imageData = await renderMiragePixels(inner, cover, mirageOptions());
    if (requestId !== state.mirageRenderRequestId) return;
    els.mirageRawCanvas.width = imageData.width;
    els.mirageRawCanvas.height = imageData.height;
    const rawContext = els.mirageRawCanvas.getContext("2d");
    if (!rawContext) throw new Error("浏览器无法创建结果画布。");
    rawContext.putImageData(imageData, 0, 0);

    for (const [canvas, color] of [
      [els.mirageWhiteCanvas, "#ffffff"],
      [els.mirageBlackCanvas, "#11131a"],
    ]) {
      canvas.width = imageData.width;
      canvas.height = imageData.height;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("浏览器无法创建预览画布。");
      context.fillStyle = color;
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(els.mirageRawCanvas, 0, 0);
    }

    state.mirageOutputReady = true;
    state.mirageOutputNsfw = Boolean(inner.is_nsfw || cover.is_nsfw);
    els.mirageOutputMeta.textContent = imageData.width + " × " + imageData.height
      + " · 透明 PNG 预览 · " + (state.mirageOutputNsfw ? "NSFW 来源" : "SFW 来源");
    renderMirageCategories();
    if (state.mirageOutputNsfw && els.mirageCategory.disabled) {
      setMirageStatus("来源含 NSFW 媒体，但当前没有可保存的 NSFW 分类。请先创建或恢复一个 NSFW 分类。", true);
    } else if (state.mirageOutputNsfw) {
      setMirageStatus("预览已更新。成品导出时会从图库原图重新生成。");
    } else {
      setMirageStatus("预览已更新。保存时会从图库原图按有效分辨率生成成品。");
    }
  } catch (error) {
    if (requestId !== state.mirageRenderRequestId) return;
    clearMirageOutput();
    setMirageStatus(error.message || "生成预览失败。", true);
  }
}
function setMirageSettingsStatus(message, isError = false) {
  els.mirageSettingsStatus.textContent = message;
  els.mirageSettingsStatus.classList.toggle("error", isError);
}

async function loadMirageSettings() {
  if (state.mirageSettingsLoaded) return;
  const settings = await bridge.apiGet("mirage/settings");
  els.mirageMaxSize.value = String(settings.maxSize);
  els.mirageInnerScale.value = String(settings.scaleInner);
  els.mirageCoverScale.value = String(settings.scaleCover);
  els.mirageInnerDesat.value = String(settings.desatInner);
  els.mirageCoverDesat.value = String(settings.desatCover);
  els.mirageWeight.value = String(settings.weightInner);
  els.mirageColored.checked = settings.colored !== false;
  state.mirageSettingsLoaded = true;
  updateMirageControlLabels();
  setMirageSettingsStatus("已载入上次使用的参数；修改后会自动保存。");
}

async function saveMirageSettingsNow() {
  if (!state.mirageSettingsLoaded) return false;
  window.clearTimeout(state.mirageSettingsSaveTimer);
  state.mirageSettingsSaveTimer = 0;
  setMirageSettingsStatus("正在保存参数…");
  const settings = mirageOptions();
  const pendingSave = state.mirageSettingsSaveChain
    .catch(() => undefined)
    .then(() => bridge.apiPost("mirage/settings/save", settings));
  state.mirageSettingsSaveChain = pendingSave;
  try {
    await pendingSave;
    setMirageSettingsStatus("参数已保存，下次打开会继续使用。");
    return true;
  } catch (error) {
    setMirageSettingsStatus("参数保存失败：" + (error.message || "请稍后重试。"), true);
    return false;
  }
}

function scheduleSaveMirageSettings() {
  if (!state.mirageSettingsLoaded) return;
  window.clearTimeout(state.mirageSettingsSaveTimer);
  setMirageSettingsStatus("参数变更待保存…");
  state.mirageSettingsSaveTimer = window.setTimeout(() => {
    saveMirageSettingsNow();
  }, 450);
}

function scheduleMirageRender() {
  updateMirageControlLabels();
  window.clearTimeout(state.mirageRenderTimer);
  state.mirageRenderTimer = window.setTimeout(renderMirageOutput, 90);
  scheduleSaveMirageSettings();
}

function handleMirageColorChange() {
  renderMirageOutput();
  scheduleSaveMirageSettings();
}

function miragePickerElements(which) {
  if (which === "inner") {
    return {
      category: els.mirageInnerPickerCategory,
      grid: els.mirageInnerPickerGrid,
      previous: els.mirageInnerPickerPrevious,
      next: els.mirageInnerPickerNext,
      pageLabel: els.mirageInnerPickerPage,
      idInput: els.mirageInnerId,
      title: "里图",
    };
  }
  return {
    category: els.mirageCoverPickerCategory,
    grid: els.mirageCoverPickerGrid,
    previous: els.mirageCoverPickerPrevious,
    next: els.mirageCoverPickerNext,
    pageLabel: els.mirageCoverPickerPage,
    idInput: els.mirageCoverId,
    title: "表图",
  };
}

function populateMiragePickerCategories() {
  for (const which of ["inner", "cover"]) {
    const picker = state.miragePicker[which];
    const elements = miragePickerElements(which);
    const previousId = elements.category.value || picker.categoryId;
    elements.category.replaceChildren();
    for (const category of state.categories) {
      const option = document.createElement("option");
      option.value = category.id;
      option.textContent = category.name + (category.is_nsfw ? " · NSFW" : "");
      elements.category.append(option);
    }
    const preferred = state.categories.find((category) => category.id === previousId)
      || state.categories.find((category) => category.id === state.categoryId)
      || state.categories[0];
    picker.categoryId = preferred?.id || "";
    elements.category.value = picker.categoryId;
    elements.category.disabled = state.categories.length === 0;
  }
}

function showMiragePickerMessage(which, message) {
  const elements = miragePickerElements(which);
  const messageNode = document.createElement("p");
  messageNode.className = "hint mirage-picker-message";
  messageNode.textContent = message;
  elements.grid.replaceChildren(messageNode);
}

function renderMiragePicker(which) {
  const picker = state.miragePicker[which];
  const elements = miragePickerElements(which);
  const images = picker.items.filter((item) => item.media_type === "image");
  elements.grid.replaceChildren();

  if (!images.length) {
    showMiragePickerMessage(which, "此页没有图片；视频不会显示在选择器中。");
  } else {
    for (const item of images) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "mirage-picker-item";
      const selected = Number(state.mirageSelectedIds[which]) === Number(item.id);
      button.classList.toggle("selected", selected);
      button.setAttribute("aria-pressed", String(selected));
      button.setAttribute("aria-label", "选择" + elements.title + "，编号 " + item.id);
      button.title = "选择编号 " + item.id + " 作为" + elements.title;

      if (item.thumbnail) {
        const image = document.createElement("img");
        image.src = item.thumbnail;
        image.alt = "";
        image.loading = "lazy";
        button.append(image);
      } else {
        const placeholder = document.createElement("span");
        placeholder.className = "mirage-picker-no-thumbnail";
        placeholder.textContent = "暂无缩略图";
        button.append(placeholder);
      }

      const caption = document.createElement("span");
      caption.className = "mirage-picker-caption";
      caption.textContent = "编号 " + item.id;
      button.append(caption);
      button.addEventListener("click", () => chooseMiragePickerImage(which, item));
      elements.grid.append(button);
    }
  }

  elements.pageLabel.textContent = "第 " + picker.page + " / " + picker.pages
    + " 页 · " + images.length + " 张图片";
  elements.previous.disabled = picker.page <= 1;
  elements.next.disabled = picker.page >= picker.pages;
}

async function loadMiragePicker(which, page = 1) {
  const picker = state.miragePicker[which];
  const elements = miragePickerElements(which);
  const categoryId = elements.category.value;
  if (!categoryId) {
    picker.categoryId = "";
    picker.page = 1;
    picker.pages = 1;
    picker.items = [];
    renderMiragePicker(which);
    return;
  }

  picker.categoryId = categoryId;
  const requestId = (picker.requestId || 0) + 1;
  picker.requestId = requestId;
  showMiragePickerMessage(which, "正在读取分类缩略图…");
  try {
    const data = await bridge.apiGet("images", {
      category_id: categoryId,
      page,
      page_size: PAGE_SIZE,
      media_type: "image",
    });
    if (requestId !== picker.requestId) return;
    picker.page = data.page;
    picker.pages = data.pages;
    picker.items = Array.isArray(data.items) ? data.items : [];
    renderMiragePicker(which);
  } catch (error) {
    if (requestId !== picker.requestId) return;
    picker.items = [];
    picker.page = Math.max(1, Number(page) || 1);
    picker.pages = 1;
    renderMiragePicker(which);
    showMiragePickerMessage(which, error.message || "读取分类缩略图失败。");
  }
}

function renderMirageSourceCards() {
  for (const [which, source, preview, meta, title] of [
    ["inner", state.mirageSources.inner, els.mirageInnerPreview, els.mirageInnerMeta, "里图"],
    ["cover", state.mirageSources.cover, els.mirageCoverPreview, els.mirageCoverMeta, "表图"],
  ]) {
    if (!source) {
      preview.hidden = true;
      meta.textContent = "尚未载入图片";
      continue;
    }
    preview.src = source.data_url;
    preview.hidden = false;
    preview.alt = title + "预览，图库编号 " + source.id;
    meta.textContent = "编号 " + source.id + " · " + source.category_name
      + (source.is_nsfw ? " · NSFW" : "")
      + " · " + source.width + " × " + source.height;
  }
}

async function chooseMiragePickerImage(which, item) {
  const elements = miragePickerElements(which);
  state.mirageSelectedIds[which] = Number(item.id);
  elements.idInput.value = String(item.id);
  renderMiragePicker(which);
  const other = which === "inner" ? "cover" : "inner";
  if (Number(state.mirageSelectedIds[other]) > 0) {
    await loadMirageSources();
  } else {
    setMirageStatus("已选" + elements.title + "编号 " + item.id + "，请再选择另一张图。");
  }
}

function handleMirageIdInput(which) {
  const elements = miragePickerElements(which);
  const value = Number(elements.idInput.value);
  state.mirageSelectedIds[which] = Number.isInteger(value) && value > 0 ? value : 0;
  renderMiragePicker(which);

  const currentInnerId = String(els.mirageInnerId.value || "");
  const currentCoverId = String(els.mirageCoverId.value || "");
  const loadedSourcesMatch = state.mirageSources.inner
    && state.mirageSources.cover
    && String(state.mirageSources.inner.id) === currentInnerId
    && String(state.mirageSources.cover.id) === currentCoverId;
  if (!loadedSourcesMatch && (state.mirageSources.inner || state.mirageSources.cover)) {
    state.mirageSources = { inner: null, cover: null };
    state.mirageMaxImageBytes = 0;
    els.mirageInnerPreview.hidden = true;
    els.mirageCoverPreview.hidden = true;
    els.mirageInnerMeta.textContent = "编号已修改，请重新载入";
    els.mirageCoverMeta.textContent = "编号已修改，请重新载入";
    clearMirageOutput();
    renderMirageCategories();
    setMirageStatus("来源编号已修改，请载入两张图片后再保存。");
  }
}

async function loadMirageImage(dataUrl) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("图片预览解码失败。"));
    image.src = dataUrl;
  });
}

async function loadMirageSources() {
  const requestId = ++state.mirageSourceRequestId;
  state.mirageSources = { inner: null, cover: null };
  state.mirageMaxImageBytes = 0;
  els.mirageInnerPreview.hidden = true;
  els.mirageCoverPreview.hidden = true;
  els.mirageInnerMeta.textContent = "正在载入图片…";
  els.mirageCoverMeta.textContent = "正在载入图片…";
  clearMirageOutput();
  const innerId = Number(els.mirageInnerId.value);
  const coverId = Number(els.mirageCoverId.value);
  if (!Number.isInteger(innerId) || innerId < 1
    || !Number.isInteger(coverId) || coverId < 1) {
    els.mirageInnerMeta.textContent = "尚未载入图片";
    els.mirageCoverMeta.textContent = "尚未载入图片";
    renderMirageCategories();
    els.loadMirageSources.disabled = false;
    setMirageStatus("请输入两个有效的图库图片编号。", true);
    return;
  }
  if (innerId === coverId) {
    els.mirageInnerMeta.textContent = "尚未载入图片";
    els.mirageCoverMeta.textContent = "尚未载入图片";
    renderMirageCategories();
    els.loadMirageSources.disabled = false;
    setMirageStatus("里图和表图需要选择两张不同的图片。", true);
    return;
  }

  state.mirageSelectedIds = { inner: innerId, cover: coverId };
  renderMiragePicker("inner");
  renderMiragePicker("cover");
  els.loadMirageSources.disabled = true;
  els.mirageSave.disabled = true;
  setMirageStatus("正在读取图库图片并生成预览…");
  try {
    const readSource = async (imageId) => {
      const cacheKey = Number(imageId);
      const cached = state.mirageSourceCache.get(cacheKey);
      if (cached) {
        state.mirageSourceCache.delete(cacheKey);
        state.mirageSourceCache.set(cacheKey, cached);
        return cached;
      }
      const source = await bridge.apiPost("mirage/source", { image_id: imageId });
      const image = await loadMirageImage(source.data_url);
      const loaded = { ...source, image };
      state.mirageSourceCache.set(cacheKey, loaded);
      while (state.mirageSourceCache.size > 8) {
        const oldestKey = state.mirageSourceCache.keys().next().value;
        state.mirageSourceCache.delete(oldestKey);
      }
      return loaded;
    };
    const [inner, cover] = await Promise.all([
      readSource(innerId),
      readSource(coverId),
    ]);
    if (requestId !== state.mirageSourceRequestId) return;
    state.mirageSources = { inner, cover };
    state.mirageMaxImageBytes = Math.min(
      Number(inner.max_image_bytes || 0),
      Number(cover.max_image_bytes || 0),
    );
    renderMirageSourceCards();
    const maxMb = (state.mirageMaxImageBytes / (1024 * 1024)).toFixed(1);
    els.mirageSizeHint.textContent = "当前图片入库上限为 " + maxMb
      + " MB；成品由服务端从图库原图生成，按裁切后的较低有效分辨率输出；超过体积上限时会自动缩小并保留透明通道。";
    renderMirageOutput();
  } catch (error) {
    if (requestId !== state.mirageSourceRequestId) return;
    els.mirageInnerMeta.textContent = "尚未载入图片";
    els.mirageCoverMeta.textContent = "尚未载入图片";
    renderMirageCategories();
    setMirageStatus(error.message || "读取图库图片失败。", true);
    clearMirageOutput();
  } finally {
    if (requestId === state.mirageSourceRequestId) {
      els.loadMirageSources.disabled = false;
    }
  }
}

async function openMirageModal() {
  els.mirageModal.hidden = false;
  updateMirageControlLabels();
  renderMirageCategories();
  setMirageSettingsStatus("正在载入上次使用的参数…");
  try {
    await loadMirageSettings();
  } catch (error) {
    setMirageSettingsStatus("读取保存参数失败，暂时使用页面默认值：" + (error.message || ""), true);
  }

  populateMiragePickerCategories();
  const pickerLoads = [
    loadMiragePicker("inner", 1),
    loadMiragePicker("cover", 1),
  ];
  const selectedIds = Array.from(state.selected);
  if (selectedIds.length === 2) {
    els.mirageCoverId.value = selectedIds[0];
    els.mirageInnerId.value = selectedIds[1];
    state.mirageSelectedIds = { cover: Number(selectedIds[0]), inner: Number(selectedIds[1]) };
    loadMirageSources();
  } else if (!els.mirageInnerId.value || !els.mirageCoverId.value) {
    setMirageStatus("从两侧分类缩略图选择，或输入编号；也可先在图集中勾选两张图片。");
  }
  await Promise.allSettled(pickerLoads);
}

function closeMirageModal() {
  els.mirageModal.hidden = true;
}

async function useSelectedMirageImages() {
  const selectedIds = Array.from(state.selected);
  if (selectedIds.length !== 2) {
    setMirageStatus("请先在图集中恰好勾选两张图片，再使用此按钮。", true);
    return;
  }
  els.mirageCoverId.value = selectedIds[0];
  els.mirageInnerId.value = selectedIds[1];
  state.mirageSelectedIds = { cover: Number(selectedIds[0]), inner: Number(selectedIds[1]) };
  await loadMirageSources();
}

async function swapMirageImages() {
  const previousInnerId = String(els.mirageInnerId.value || "");
  const previousCoverId = String(els.mirageCoverId.value || "");
  if (!previousInnerId || !previousCoverId) {
    setMirageStatus("先载入或选择里图和表图，再进行互换。", true);
    return;
  }

  const canSwapLoadedSources = state.mirageSources.inner
    && state.mirageSources.cover
    && String(state.mirageSources.inner.id) === previousInnerId
    && String(state.mirageSources.cover.id) === previousCoverId;
  els.mirageInnerId.value = previousCoverId;
  els.mirageCoverId.value = previousInnerId;
  state.mirageSelectedIds = {
    inner: Number(previousCoverId),
    cover: Number(previousInnerId),
  };
  renderMiragePicker("cover");
  renderMiragePicker("inner");

  if (!canSwapLoadedSources) {
    await loadMirageSources();
    return;
  }

  state.mirageSources = {
    inner: state.mirageSources.cover,
    cover: state.mirageSources.inner,
  };
  renderMirageSourceCards();
  renderMirageOutput();
  setMirageStatus("里图和表图已互换，预览已更新。");
}

async function saveMirageToGallery() {
  const category = state.categories.find((item) => item.id === els.mirageCategory.value);
  if (!state.mirageOutputReady || !category) {
    setMirageStatus("请先载入两张图片，并选择有效的保存分类。", true);
    return;
  }
  if (state.mirageOutputNsfw && !category.is_nsfw) {
    setMirageStatus("NSFW 来源的成品只能保存到 NSFW 分类。", true);
    renderMirageCategories();
    return;
  }

  els.mirageSave.disabled = true;
  setMirageStatus("正在从图库原图生成透明 PNG…");
  try {
    await saveMirageSettingsNow();
    const innerId = state.mirageSources.inner.id;
    const coverId = state.mirageSources.cover.id;
    const result = await bridge.apiPost("mirage/save", {
      cover_id: coverId,
      inner_id: innerId,
      category_id: category.id,
      settings: mirageOptions(),
    });
    closeMirageModal();
    state.trashMode = false;
    state.duplicateMode = false;
    state.searchActive = false;
    state.searchQuery = "";
    state.tagFilter = "";
    state.page = 1;
    els.galleryPanel.hidden = false;
    els.duplicatePanel.hidden = true;
    els.tagTaxonomyPanel.hidden = true;
    els.activeToolbar.hidden = false;
    els.activeSearchPanel.hidden = false;
    els.activeSelectionActions.hidden = false;
    els.trashActions.hidden = true;
    try {
      await loadCategories(category.id);
    } catch (error) {
      showNotice("成品已生成，但刷新图库失败：" + (error.message || "请手动刷新。"), "error", 0);
      return;
    }
    const outputSize = result.mirage_width && result.mirage_height
      ? "（" + result.mirage_width + " × " + result.mirage_height + "）"
      : "";
    showNotice(
      result.duplicate
        ? "该幻影坦克图片已存在于「" + category.name + "」，跳过重复项。"
        : "幻影坦克 PNG 已保存到「" + category.name + "」" + outputSize + "。",
      "success",
    );
  } catch (error) {
    setMirageStatus(error.message || "保存幻影坦克失败。", true);
  } finally {
    if (!els.mirageModal.hidden) {
      els.mirageSave.disabled = !state.mirageOutputReady;
    }
  }
}
els.openMirage.addEventListener("click", () => {
  openMirageModal().catch((error) => {
    setMirageStatus(error.message || "打开幻影坦克制作失败。", true);
  });
});
els.closeMirage.addEventListener("click", closeMirageModal);
els.mirageModal.addEventListener("click", (event) => {
  if (event.target === els.mirageModal) closeMirageModal();
});
els.useSelectedMirage.addEventListener("click", () => {
  useSelectedMirageImages().catch((error) => {
    setMirageStatus(error.message || "读取已选图片失败。", true);
  });
});
els.swapMirage.addEventListener("click", () => {
  swapMirageImages().catch((error) => {
    setMirageStatus(error.message || "交换图片失败。", true);
  });
});
els.loadMirageSources.addEventListener("click", loadMirageSources);
els.mirageInnerId.addEventListener("input", () => handleMirageIdInput("inner"));
els.mirageCoverId.addEventListener("input", () => handleMirageIdInput("cover"));
for (const which of ["inner", "cover"]) {
  const picker = miragePickerElements(which);
  picker.category.addEventListener("change", () => loadMiragePicker(which, 1));
  picker.previous.addEventListener("click", () => {
    loadMiragePicker(which, state.miragePicker[which].page - 1);
  });
  picker.next.addEventListener("click", () => {
    loadMiragePicker(which, state.miragePicker[which].page + 1);
  });
}
els.mirageSave.addEventListener("click", saveMirageToGallery);
for (const input of [
  els.mirageMaxSize,
  els.mirageInnerScale,
  els.mirageCoverScale,
  els.mirageInnerDesat,
  els.mirageCoverDesat,
  els.mirageWeight,
]) {
  input.addEventListener("input", scheduleMirageRender);
}
els.mirageColored.addEventListener("change", handleMirageColorChange);
els.mirageCategory.addEventListener("change", () => {
  els.mirageSave.disabled = !state.mirageOutputReady || !els.mirageCategory.value;
});
els.openTaskCenter.addEventListener("click", openTaskCenter);
els.refreshButton.addEventListener("click", refresh);
els.closeTaskCenter.addEventListener("click", closeTaskCenter);
els.refreshTasks.addEventListener("click", () => {
  loadTaskCenter().catch((error) => showNotice(error.message || "刷新任务失败。", "error", 0));
});
els.taskCenterModal.addEventListener("click", (event) => {
  if (event.target === els.taskCenterModal) closeTaskCenter();
});
els.reassessSfw.addEventListener("click", () => reassessStaleMedia("sfw"));
els.reassessNsfw.addEventListener("click", () => reassessStaleMedia("nsfw"));
els.taskNsfwProvider.addEventListener("change", () => {
  if (state.taskCenterOpen) loadTaskCenter().catch((error) => showNotice(error.message, "error", 0));
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.taskCenterOpen) closeTaskCenter();
  if (event.key === "Escape" && !els.mirageModal.hidden) closeMirageModal();
});
els.categorySelect.addEventListener("change", async () => {
  state.categoryId = els.categorySelect.value;
  state.searchActive = false;
  state.tagFilter = "";
  state.page = 1;
  try { await loadImages(); } catch (error) { showNotice(error.message, "error", 0); }
  const category = selectedCategory();
  els.deleteCategory.disabled = !category || category.id === "pending";
  renderMoveTargets();
});
els.semanticSearch.addEventListener("click", runSemanticSearch);
els.rebuildSfwIndex.addEventListener("click", () => rebuildEmbeddingIndex("sfw"));
els.rebuildNsfwIndex.addEventListener("click", () => rebuildEmbeddingIndex("nsfw"));
els.semanticQuery.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    runSemanticSearch();
  }
});
els.clearSearch.addEventListener("click", async () => {
  state.searchActive = false;
  state.page = 1;
  try { await loadImages(); } catch (error) { showNotice(error.message, "error", 0); }
});
els.clearTagFilter.addEventListener("click", async () => {
  state.tagFilter = "";
  state.page = 1;
  try { await loadImages(); } catch (error) { showNotice(error.message, "error", 0); }
});
els.nsfwProvider.addEventListener("change", () => {
  updateSelectionControls();
});
els.evaluateSelected.addEventListener("click", async () => {
  const ids = [...state.selected];
  if (!ids.length || !els.nsfwProvider.value) return;
  const accepted = await confirmAction(
    "提交 NSFW 媒体进行人工评估？",
    `将把所选 ${ids.length} 个 NSFW 媒体（视频会发送最多 3 张抽帧）发送给“${els.nsfwProvider.selectedOptions[0]?.textContent || els.nsfwProvider.value}”。`,
    "确认并评估",
  );
  if (!accepted) return;
  try {
    const result = await bridge.apiPost("ai/evaluate", {
      image_ids: ids,
      scope: "nsfw",
      provider_id: els.nsfwProvider.value,
    });
    state.selected.clear();
    await loadImages();
    showNotice(`NSFW 评估：${result.scheduled} 个加入队列，${result.skipped_existing} 个已有描述或正在评估，已跳过。`, "success", 7000);
  } catch (error) {
    showNotice(error.message || "NSFW 人工评估提交失败。", "error", 0);
  }
});
els.evaluateSfwSelected.addEventListener("click", async () => {
  const ids = [...state.selected];
  if (!ids.length || !state.sfwProviderId) return;
  const accepted = await confirmAction(
    "评估所选 SFW 媒体？",
    `将把所选 ${ids.length} 个 SFW 媒体（视频会发送最多 3 张抽帧）发送给插件配置中的视觉模型。`,
    "确认并评估",
  );
  if (!accepted) return;
  try {
    const result = await bridge.apiPost("ai/evaluate", {
      image_ids: ids,
      scope: "sfw",
    });
    state.selected.clear();
    await loadImages();
    showNotice(`SFW 评估：${result.scheduled} 个加入队列，${result.skipped_existing} 个已有描述或正在评估，已跳过。`, "success", 7000);
  } catch (error) {
    showNotice(error.message || "SFW 评估提交失败。", "error", 0);
  }
});
els.moveTarget.addEventListener("change", () => {
  state.targetCategoryId = els.moveTarget.value;
  updateSelectionControls();
});
document.querySelector("#createCategoryButton").addEventListener("click", openCategoryModal);
document.querySelector("#closeModalButton").addEventListener("click", closeCategoryModal);
document.querySelector("#cancelModalButton").addEventListener("click", closeCategoryModal);
els.categoryModal.addEventListener("click", (event) => {
  if (event.target === els.categoryModal) closeCategoryModal();
});

els.categoryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = els.categoryName.value.trim();
  if (!name) return;
  try {
    const category = await bridge.apiPost("categories/create", {
      name,
      is_nsfw: els.categoryNsfw.checked,
    });
    closeCategoryModal();
    state.page = 1;
    await loadCategories(category.id);
    showNotice(`已创建分类「${category.name}」。`);
  } catch (error) {
    showNotice(error.message || "创建分类失败。", "error", 0);
  }
});

els.editTags.addEventListener("click", () => {
  if (state.selected.size >= 2) openTagsModal([...state.selected]);
});
document.querySelector("#closeTagsModalButton").addEventListener("click", closeTagsModal);
document.querySelector("#cancelTagsModalButton").addEventListener("click", closeTagsModal);
els.tagsModal.addEventListener("click", (event) => {
  if (event.target === els.tagsModal) closeTagsModal();
});
els.tagsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.tagTargetIds.length) return;
  try {
    const result = await bridge.apiPost("images/tags", {
      image_ids: state.tagTargetIds,
      tags: els.tagsInput.value,
      mode: els.tagMode.value,
    });
    closeTagsModal();
    state.selected.clear();
    await loadImages();
    const indexNotice = result.embedding_scheduled ? ` 已提交 ${result.embedding_scheduled} 项语义索引更新。` : "";
    showNotice(`已更新 ${result.updated} 个媒体的手工标签。${indexNotice}`);
  } catch (error) {
    showNotice(error.message || "保存标签失败。", "error", 0);
  }
});

document.querySelector("#closeDetailModalButton").addEventListener("click", closeDetailModal);
document.querySelector("#cancelDetailModalButton").addEventListener("click", closeDetailModal);
els.addDetailManualTag.addEventListener("click", addDetailManualTag);
els.detailManualTagInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.isComposing) {
    event.preventDefault();
    addDetailManualTag();
  }
});
els.detailModal.addEventListener("click", (event) => {
  if (event.target === els.detailModal) closeDetailModal();
});
els.clearAiEvaluation.addEventListener("click", async () => {
  if (!state.detailItemId || state.clearAiEvaluation) return;
  state.clearAiEvaluation = true;
  state.detailAiTags = [];
  els.detailDescription.value = "";
  els.clearAiEvaluation.disabled = true;
  els.clearAiEvaluationHint.textContent = "已选择清空 AI 描述和标签。点击“保存详情”后生效，手工标签会保留。";
  renderDetailAiTags();
});
els.detailForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.detailItemId) return;
  try {
    const preferredCategoryId = state.detailCategoryId;
    const result = await bridge.apiPost("images/details", {
      image_id: state.detailItemId,
      description: els.detailDescription.value,
      manual_tags: state.detailManualTags,
      ai_tags: state.detailAiTags,
      clear_ai: state.clearAiEvaluation,
    });
    closeDetailModal();
    state.selected.clear();
    if (result.ai_cleared) {
      state.searchActive = false;
      state.tagFilter = "";
      state.page = 1;
      await loadCategories(preferredCategoryId);
      showNotice(result.can_evaluate
        ? "AI 描述和标签已清空，手工标签已保留；选择该媒体后可以重新评估。"
        : "AI 数据已清空；该媒体仍有手动描述或处于待处理分类，暂不能重新评估。", "success", 7000);
    } else {
      await loadImages();
      showNotice(result.embedding_scheduled
        ? "描述及 AI/手工标签已保存，语义索引任务已提交；可在 AI 任务中心查看进度。"
        : "描述及 AI/手工标签已保存；当前未建立语义索引。", "success", 7000);
    }
  } catch (error) {
    showNotice(error.message || "保存媒体详情失败。", "error", 0);
  }
});

els.deleteCategory.addEventListener("click", async () => {
  const category = selectedCategory();
  if (!category || category.id === "pending") return;
  const accepted = await confirmAction(
    "删除这个分类？",
    `删除后，${category.image_count} 个媒体会转入「待处理」。相同文件会合并，NSFW 标记会保留。`,
  );
  if (!accepted) return;
  try {
    const result = await bridge.apiPost("categories/delete", { category_id: category.id });
    state.categoryId = "";
    state.page = 1;
    await loadCategories();
    showNotice(`已删除「${category.name}」；${result.moved} 个移入待处理，${result.merged} 个重复项合并。`);
  } catch (error) {
    showNotice(error.message || "删除分类失败。", "error", 0);
  }
});

els.tagTaxonomyButton.addEventListener("click", openTagTaxonomyPanel);
els.tagTaxonomyBack.addEventListener("click", async () => {
  els.tagTaxonomyPanel.hidden = true;
  els.activeToolbar.hidden = false;
  els.activeSearchPanel.hidden = false;
  els.galleryPanel.hidden = false;
  try { await loadImages(); } catch (error) { showNotice(error.message, "error", 0); }
});
els.tagAliasForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await bridge.apiPost("tags/aliases/save", {
      alias: els.tagAliasInput.value,
      canonical_tag: els.tagCanonicalInput.value,
    });
    els.tagAliasInput.value = "";
    els.tagCanonicalInput.value = "";
    clearTagNormalizationPreview();
    await loadTagTaxonomy();
    showNotice("已保存别名；现存标签未改写。");
  } catch (error) {
    showNotice(error.message || "保存标签别名失败。", "error", 0);
  }
});
els.tagAliasList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-alias]");
  if (!button) return;
  try {
    await bridge.apiPost("tags/aliases/delete", { alias: button.dataset.alias });
    clearTagNormalizationPreview();
    await loadTagTaxonomy();
    showNotice("已删除别名规则；媒体标签未改写。");
  } catch (error) {
    showNotice(error.message || "删除标签别名失败。", "error", 0);
  }
});
els.tagHierarchyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await bridge.apiPost("tags/hierarchy/save", {
      child_tag: els.tagChildInput.value,
      parent_tag: els.tagParentInput.value,
    });
    els.tagChildInput.value = "";
    els.tagParentInput.value = "";
    await loadTagTaxonomy();
    showNotice("已保存层级；现存标签未改写。");
  } catch (error) {
    showNotice(error.message || "保存标签层级失败。", "error", 0);
  }
});
els.tagHierarchyList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-child-tag]");
  if (!button) return;
  try {
    await bridge.apiPost("tags/hierarchy/delete", { child_tag: button.dataset.childTag });
    await loadTagTaxonomy();
    showNotice("已删除标签层级规则。");
  } catch (error) {
    showNotice(error.message || "删除标签层级失败。", "error", 0);
  }
});
els.previewTagNormalization.addEventListener("click", async () => {
  try {
    const plan = await bridge.apiPost("tags/normalize/preview", {});
    renderTagNormalizationPreview(plan);
  } catch (error) {
    showNotice(error.message || "生成标签规范化预览失败。", "error", 0);
  }
});
els.applyTagNormalization.addEventListener("click", async () => {
  const plan = state.tagNormalizationPlan;
  const planToken = plan?.plan_token || plan?.token;
  if (!planToken || !plan.updated_tags) {
    showNotice("规范化预览令牌缺失，请重新点击“预览规范化”。", "error", 0);
    return;
  }
  const accepted = await confirmAction(
    "确认批量规范化标签？",
    "将按预览把 " + plan.updated_tags + " 个存量标签统一为规范标签，影响 "
      + plan.updated_media + " 个媒体。该操作会改写图片/视频和回收站中的标签；AI 标签变化后需重建对应语义索引。",
    "确认规范化",
  );
  if (!accepted) return;
  try {
    const result = await bridge.apiPost("tags/normalize/apply", {
      confirm: true,
      plan_token: planToken,
    });
    clearTagNormalizationPreview();
    await loadTagTaxonomy();
    showNotice("已规范化 " + result.updated_tags + " 个标签，影响 "
      + result.updated_media + " 个媒体；" + result.invalidated_embeddings
      + " 个语义索引已失效，请按需重建。", "success", 9000);
  } catch (error) {
    clearTagNormalizationPreview();
    showNotice(error.message || "批量规范化失败，请重新预览。", "error", 0);
  }
});
els.useCanonicalDetailTag.addEventListener("click", () => {
  els.detailManualTagInput.value = els.useCanonicalDetailTag.dataset.canonicalTag || "";
  updateDetailTagAliasHint();
  els.detailManualTagInput.focus();
});
els.useCanonicalBulkTag.addEventListener("click", () => {
  const raw = els.tagsInput.value;
  const splitAt = Math.max(raw.lastIndexOf(","), raw.lastIndexOf("，"), raw.lastIndexOf("、"));
  const prefix = splitAt >= 0 ? raw.slice(0, splitAt + 1) + " " : "";
  els.tagsInput.value = prefix + (els.useCanonicalBulkTag.dataset.canonicalTag || "");
  updateBulkTagAliasHint();
  els.tagsInput.focus();
});
els.detailManualTagInput.addEventListener("input", updateDetailTagAliasHint);
els.tagsInput.addEventListener("input", updateBulkTagAliasHint);

els.duplicateCheck.addEventListener("click", openDuplicatePanel);
els.duplicateBack.addEventListener("click", async () => {
  state.duplicateMode = false;
  els.duplicatePanel.hidden = true;
  els.galleryPanel.hidden = false;
  els.activeToolbar.hidden = false;
  els.activeSearchPanel.hidden = false;
  try { await loadImages(); } catch (error) { showNotice(error.message, "error", 0); }
});
els.startDuplicateScan.addEventListener("click", startDuplicateScan);
els.exactDuplicatesTab.addEventListener("click", async () => {
  state.duplicateKind = "exact";
  state.duplicatePage = 1;
  try { await loadDuplicateResults(); } catch (error) { showNotice(error.message, "error", 0); }
});
els.similarImagesTab.addEventListener("click", async () => {
  state.duplicateKind = "similar";
  state.duplicatePage = 1;
  try { await loadDuplicateResults(); } catch (error) { showNotice(error.message, "error", 0); }
});
els.duplicateSelectAll.addEventListener("click", () => changeDuplicateSelection("all"));
els.duplicateInvertSelection.addEventListener("click", () => changeDuplicateSelection("invert"));
els.duplicateClearSelection.addEventListener("click", () => changeDuplicateSelection("clear"));
els.duplicateTrash.addEventListener("click", trashDuplicateSelection);
els.duplicatePreviousPage.addEventListener("click", async () => {
  if (state.duplicatePage <= 1) return;
  state.duplicatePage -= 1;
  try { await loadDuplicateResults(); } catch (error) { showNotice(error.message, "error", 0); }
});
els.duplicateNextPage.addEventListener("click", async () => {
  if (state.duplicatePage >= state.duplicatePages) return;
  state.duplicatePage += 1;
  try { await loadDuplicateResults(); } catch (error) { showNotice(error.message, "error", 0); }
});

els.selectAll.addEventListener("click", () => changeVisibleSelection("all"));
els.invertSelection.addEventListener("click", () => changeVisibleSelection("invert"));
els.clearSelection.addEventListener("click", () => changeVisibleSelection("clear"));
els.trashSelectAll.addEventListener("click", () => changeVisibleSelection("all"));
els.trashInvertSelection.addEventListener("click", () => changeVisibleSelection("invert"));
els.trashClearSelection.addEventListener("click", () => changeVisibleSelection("clear"));
els.openTrash.addEventListener("click", async () => {
  state.trashMode = true;
  state.searchActive = false;
  state.page = 1;
  try { await loadImages(); } catch (error) { showNotice(error.message, "error", 0); }
});
els.trashBack.addEventListener("click", async () => {
  state.trashMode = false;
  state.page = 1;
  try { await loadCategories(); } catch (error) { showNotice(error.message, "error", 0); }
});
els.restoreTrashSelected.addEventListener("click", () => restoreTrash([...state.selected]));
els.purgeTrashSelected.addEventListener("click", () => permanentlyDeleteTrash([...state.selected]));
els.emptyTrash.addEventListener("click", emptyTrash);

els.deleteImages.addEventListener("click", async () => {
  const ids = [...state.selected];
  if (!ids.length) return;
  const accepted = await confirmAction(
    "将所选媒体移入回收站？",
    `所选 ${ids.length} 个媒体可从回收站还原；回收站会在每日 0 点自动清空。`,
    "移入回收站",
  );
  if (!accepted) return;
  try {
    const result = await bridge.apiPost("images/delete", { image_ids: ids });
    state.selected.clear();
    await loadCategories();
    showNotice(`已将 ${result.trashed} 个媒体移入回收站。`);
  } catch (error) {
    showNotice(error.message || "移入回收站失败。", "error", 0);
  }
});

els.moveImages.addEventListener("click", async () => {
  const ids = [...state.selected];
  const target = state.categories.find((category) => category.id === state.targetCategoryId);
  if (!ids.length || !target) return;
  const accepted = await confirmAction(
    "移动所选媒体？",
    `将尝试把 ${ids.length} 个媒体移入「${target.name}」。目标分类已有的重复项会跳过。`,
    "确认移动",
  );
  if (!accepted) return;
  try {
    const result = await bridge.apiPost("images/move", {
      image_ids: ids,
      target_category_id: target.id,
    });
    state.selected.clear();
    await loadCategories();
    showNotice(
      `移动完成：${result.moved} 个已移动，${result.nsfw_marks_cleared || 0} 个已清除 NSFW 标记，${result.skipped_duplicates} 个因重复跳过，${result.already_in_target} 个原本就在目标分类。`,
      "success",
    );
  } catch (error) {
    showNotice(error.message || "批量移动失败。", "error", 0);
  }
});

els.previousPage.addEventListener("click", async () => {
  if (state.page <= 1) return;
  state.page -= 1;
  try { await loadImages(); } catch (error) { showNotice(error.message, "error", 0); }
});
els.nextPage.addEventListener("click", async () => {
  if (state.page >= state.pages) return;
  state.page += 1;
  try { await loadImages(); } catch (error) { showNotice(error.message, "error", 0); }
});

els.uploadButton.addEventListener("click", () => {
  if (!state.categoryId) {
    showNotice("请先选择或创建一个分类。", "error");
    return;
  }
  els.fileInput.click();
});

const LARGE_UPLOAD_CHUNK_THRESHOLD = 32 * 1024 * 1024;
const UPLOAD_STATUS_POLL_MS = 1000;
const UPLOAD_JOB_TIMEOUT_MS = 35 * 60 * 1000;

function delay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function uploadChunkWithRetry(path, chunk, fileNumber, fileCount, filename, index, total) {
  let lastError;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      return await bridge.upload(path, chunk);
    } catch (error) {
      lastError = error;
      if (attempt < 2) {
        showNotice(
          "分块上传遇到网络波动，正在重试 " + fileNumber + "/" + fileCount
            + "：" + filename + "（" + (index + 1) + "/" + total + "）",
          "success",
          0,
        );
        await delay(600 * (attempt + 1));
      }
    }
  }
  throw lastError;
}

function uploadMediaType(file) {
  const videoSuffix = /\.(mp4|mov|3gp|avi|mkv|webm)$/i.test(file.name);
  return file.type.startsWith("video/") || videoSuffix ? "video" : "image";
}

async function waitForUploadJob(job, filename, fileNumber, fileCount) {
  if (!job?.job_id) return job;
  const startedAt = Date.now();
  while (Date.now() - startedAt < UPLOAD_JOB_TIMEOUT_MS) {
    let status;
    let statusError;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        status = await bridge.apiGet("upload/status", { job_id: job.job_id });
        statusError = null;
        break;
      } catch (error) {
        statusError = error;
        if (attempt < 2) await delay(500 * (attempt + 1));
      }
    }
    if (statusError) {
      throw new Error("读取导入状态失败：" + (statusError.message || "网络连接中断。"));
    }
    if (status.status === "completed") return status.result;
    if (status.status === "failed") {
      throw new Error(status.error || "导入失败。");
    }
    showNotice(
      "服务器正在处理 " + fileNumber + "/" + fileCount + "：" + filename + "（压缩/入库中…）",
      "success",
      0,
    );
    await delay(UPLOAD_STATUS_POLL_MS);
  }
  throw new Error("服务器处理时间较长，请刷新分类确认媒体是否已入库。");
}

async function uploadOneMedia(file, categoryId, fileNumber, fileCount) {
  if (file.size <= LARGE_UPLOAD_CHUNK_THRESHOLD) {
    const job = await bridge.upload(
      "categories/" + categoryId + "/upload",
      file,
    );
    return waitForUploadJob(job, file.name, fileNumber, fileCount);
  }

  const session = await bridge.apiPost(
    "categories/" + categoryId + "/upload/start",
    {
      filename: file.name,
      size_bytes: file.size,
      media_type: uploadMediaType(file),
      content_type: file.type,
    },
  );
  try {
    for (let index = 0; index < session.total_chunks; index += 1) {
      const start = index * session.chunk_size;
      const end = Math.min(file.size, start + session.chunk_size);
      const chunk = new File(
        [file.slice(start, end)],
        file.name + ".part-" + index,
        { type: "application/octet-stream" },
      );
      showNotice(
        "正在分块上传 " + fileNumber + "/" + fileCount + "：" + file.name
          + "（" + (index + 1) + "/" + session.total_chunks + "）",
        "success",
        0,
      );
      await uploadChunkWithRetry(
        "categories/" + categoryId + "/upload/chunk/"
          + encodeURIComponent(session.upload_id) + "/" + index,
        chunk,
        fileNumber,
        fileCount,
        file.name,
        index,
        session.total_chunks,
      );
    }
    const job = await bridge.apiPost(
      "categories/" + categoryId + "/upload/complete",
      { upload_id: session.upload_id },
    );
    return await waitForUploadJob(job, file.name, fileNumber, fileCount);
  } catch (error) {
    try {
      await bridge.apiPost("upload/cancel", { upload_id: session.upload_id });
    } catch {
      // The server expires abandoned chunk sessions automatically.
    }
    throw error;
  }
}

els.fileInput.addEventListener("change", async () => {
  const files = [...els.fileInput.files];
  els.fileInput.value = "";
  if (!files.length) return;
  const categoryId = state.categoryId;
  let imported = 0;
  let duplicates = 0;
  let compressed = 0;
  let savedBytes = 0;
  const failures = [];
  els.uploadButton.disabled = true;
  try {
    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      showNotice("正在导入 " + (index + 1) + "/" + files.length + "：" + file.name, "success", 0);
      try {
        const result = await uploadOneMedia(file, categoryId, index + 1, files.length);
        if (result.duplicate) {
          duplicates += 1;
        } else {
          imported += 1;
          if (result.compressed) {
            compressed += 1;
            savedBytes += Math.max(
              0,
              Number(result.original_size_bytes || 0) - Number(result.size_bytes || 0),
            );
          }
        }
      } catch (error) {
        failures.push(file.name + "：" + (error.message || "导入失败"));
      }
    }
    state.page = 1;
    await loadCategories(categoryId);
    const compressionSummary = compressed
      ? "，自动压缩 " + compressed + " 项，节省 " + formatBytes(savedBytes)
      : "";
    const summary = "导入完成：新增 " + imported + " 项，重复跳过 "
      + duplicates + " 项" + compressionSummary + "，失败 " + failures.length + " 项。";
    showNotice(
      failures.length ? summary + " " + failures.slice(0, 3).join("；") : summary,
      failures.length ? "error" : "success",
      failures.length ? 0 : 7000,
    );
  } catch (error) {
    showNotice(error.message || "刷新媒体列表失败。", "error", 0);
  } finally {
    els.uploadButton.disabled = false;
  }
});

await bridge.ready();
try {
  await loadAiProviders();
} catch (error) {
  showNotice(error.message || "读取 AI 模型列表失败。", "error", 0);
}
await refresh();
