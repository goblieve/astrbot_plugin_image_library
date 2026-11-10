const bridge = window.AstrBotPluginView;
const PAGE_SIZE = 30;

const els = {
  notice: document.querySelector("#notice"),
  categorySelect: document.querySelector("#categorySelect"),
  galleryTitle: document.querySelector("#galleryTitle"),
  gallerySummary: document.querySelector("#gallerySummary"),
  grid: document.querySelector("#imageGrid"),
  emptyState: document.querySelector("#emptyState"),
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
  detailItemId: null,
  detailCategoryId: "",
  clearAiEvaluation: false,
  detailAiTags: [],
  detailManualTags: [],
  trashMode: false,
  tagProviders: [],
  sfwProviderId: "",
  noticeTimer: 0,
  embeddingBusy: false,
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

function openTagsModal(imageIds) {
  state.tagTargetIds = [...new Set(imageIds.map(Number))];
  if (state.tagTargetIds.length < 2) {
    state.tagTargetIds = [];
    return;
  }
  els.tagsModalTitle.textContent = `批量维护 ${state.tagTargetIds.length} 个媒体的标签`;
  els.tagMode.value = "add";
  els.tagsInput.value = "";
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
  els.detailManualTagsHint.textContent = "按 Enter 或点击“添加”保存标签；每个标签最多 32 个字符，每个媒体最多保留 30 个手工标签。AI 标签与手工标签分开保存。";
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
  els.detailManualTagsHint.textContent = "按 Enter 或点击“添加”保存标签；每个标签最多 32 个字符，每个媒体最多保留 30 个手工标签。AI 标签与手工标签分开保存。";
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
      els.reindexStatus.textContent = `正在重建 ${scopeLabel} 索引：${latest.processed} / ${latest.total}（成功 ${latest.indexed}，失败 ${latest.failed}）`;
    }
    if (latest.status === "completed") {
      els.reindexStatus.textContent = `重建完成：成功 ${latest.indexed}，失败 ${latest.failed}。`;
      showNotice(`${scopeLabel} 索引重建完成：成功 ${latest.indexed}，失败 ${latest.failed}。`, latest.failed ? "error" : "success", 0);
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

document.querySelector("#refreshButton").addEventListener("click", refresh);
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
    showNotice(`已更新 ${result.updated} 个媒体的手工标签。`);
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
      showNotice(result.embedding_indexed
        ? "描述及 AI/手工标签已保存，语义索引已更新。"
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
