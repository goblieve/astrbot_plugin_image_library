# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses Semantic Versioning.

## [1.1.3] - 2026-11-10

### Added

- Added a persistent AI processing task center for media compression, video preview generation, AI evaluation, and semantic indexing, with task progress, status, error details, retry, and cancellation.
- Recorded the model ID, prompt hash, and timestamps for AI evaluations. Added stale-evaluation detection so only content evaluated with an older model or prompt needs reassessment; NSFW reassessment remains a manual, model-selected action.
- Added tag aliases and optional parent-child tag relationships, manual and batch tag maintenance, fuzzy tag search with the 搜图 command, and semantic search.
- Added cross-category duplicate checks for exact matches and visually similar images.
- Added a recycle bin with restore and permanent-delete controls, plus scheduled daily cleanup.
- Added personal WeChat (weixin_oc) support and unified image/video collection, browsing, and category storage.
- Added configurable handling for oversized uploads, including optional automatic compression and chunked WebUI uploads for large media.

### Changed

- Updated chat commands so most commands no longer require the 图集 prefix; retained 图集 帮助 and 图集 删除.
- Added separate SFW and NSFW evaluation model and prompt settings. SFW media can be evaluated automatically; NSFW media requires a manual selection and confirmation.
- Expanded WebUI bulk operations for media import, category moves, selection, and management.

### Fixed

- Placed reassessment confirmation dialogs above the AI processing task center so they remain visible while the task center is open.
- Improved large-media import and compression handling, and made task progress reflect completion of the full ingest operation rather than compression alone.
- Prevented cancellation of one semantic-index task from cancelling the rest of a batch.
