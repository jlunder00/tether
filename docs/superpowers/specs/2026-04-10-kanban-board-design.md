# Kanban Board + Programmable Columns (Phase 9) — Design Spec

## Core Architecture

### Columns
- Horizontal scroll layout, arbitrary number of columns
- User-definable with programmable rules
- Default columns: Backlog, Pending, In Progress, Skipped, Done
- Each column has **entry rules**: auto-modifications to task fields when a task enters
  - Default: change status + prompt for scheduling if unscheduled
  - Users can add custom auto-modifications to any detail field on column entry
- Columns are collapsible/hideable

### Grouping (within columns)
- **Primary group**: context entry
- **Sub-group**: milestone (using milestone colors)
- Milestone sub-groups shown as colored bubble headings — tasks under same milestone auto-merge when dragged next to the heading
- Context headings have same auto-placement logic
- No milestone label needed per task — the heading provides it
- Condensed, clean view

### Selection & Multi-Drag
- Multi-select for bulk moves between columns
- Double-click milestone heading → selects all tasks under it
- Double-click context heading → selects all under that context
- Elegant multi-scheduling popup for bulk backlog→scheduled moves

### Drag Behavior
- **Between scheduled columns**: auto-applies column entry rules (status change by default)
- **Backlog → scheduled column**: prompts to schedule (date+anchor picker) by default, but:
  - User can configure whether prompt appears
  - Scheduling is **optional** — unscheduled tasks can exist anywhere on the kanban
- Column entry modifications are **programmable**: default is status change + schedule prompt, but users can define any auto-modification to any field
- Multi-drag: elegant bulk scheduling popup

### Dashboard Integration
- Dashboard boxes **inherit kanban columns** with filtering applied:
  - **Now box** = In Progress column filtered to current anchor's tasks
  - **Today box** = Pending column filtered to today's date
  - **This Week box** = Pending column filtered to this week
- User-customizable: choose which columns/filters appear on dashboard
- Overdue highlighting on dashboard (tasks past their scheduled date, not done)

### Mobile
- **Fix horizontal scrolling** (currently broken when content too wide)
- Mobile-friendly detail panels
- **Anchor labels**: change from big rectangles to compact pill headings for their section (better on both desktop and mobile)
- Kanban columns may need tab-based navigation on narrow screens

## Implementation Phases

### Phase A: Column Infrastructure + Default Lifecycle Columns
- `kanban_columns` DB table: id, name, position, rules_json, color
- Default seed: Backlog, Pending, In Progress, Done, Skipped
- KanbanView.vue: horizontal scroll container with column components
- Route: `/kanban`
- Basic task rendering in columns (by status mapping)

### Phase B: Grouping (Context + Milestone Sub-Groups)
- Within each column: group by context entry
- Sub-group by milestone with colored bubble headings
- Auto-placement: dragging task next to a milestone heading merges it into that group
- Context headings with same behavior

### Phase C: Drag-Drop with Column Entry Rules + Schedule Picker
- Drag between columns applies entry rules
- Schedule picker popover when moving unscheduled → scheduled column
- Configurable: user can disable schedule prompt per column
- Entry rules stored as JSON in column definition

### Phase D: Multi-Select + Bulk Operations
- Shift+click / Ctrl+click for multi-select
- Double-click headings to select group
- Bulk drag with multi-scheduling popup
- Bulk status change

### Phase E: Dashboard Inherits Kanban Columns with Filters
- Dashboard boxes become filtered views of kanban columns
- Now = In Progress + current anchor filter
- Today = Pending + today filter
- This Week = Pending + this week filter
- User-customizable column/filter selection

### Phase F: User-Defined Columns + Programmable Rules
- UI for creating/editing columns
- Rule editor: entry conditions, auto-modifications
- Column ordering/visibility toggle

### Phase G: Mobile Fixes
- Fix horizontal scrolling across all views
- Anchor labels → compact pill headings
- Responsive detail panels
- Tab-based kanban navigation on narrow screens

## Deferred
- Tags table + arbitrary tagging (feeds into grouping/filtering)
- Backlog categories (replaced by column system — Backlog column IS the category)
- Anchor descriptions + task templates
- Bot scheduling from kanban categories
