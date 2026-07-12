# First-time user experience review

Review date: 2026-07-12

## Findings and improvements

| Area | First-time problem | Improvement |
| --- | --- | --- |
| Workflow | The dashboard showed controls without explaining the next valid step. | Added status-specific next-step guidance and clearer success messages after analysis and generation. |
| Onboarding | An empty tracker only told users to import through the API. | Added a three-step first-run path and a direct link to interactive API setup documentation. No import/profile functionality was added. |
| Navigation | Mobile CSS removed all section navigation. | Kept a compact horizontal Overview, Applications, and Approval navigation on small screens. |
| Loading | Document changes, refreshes, AI generation, and analysis lacked visible progress. | Added initial, refresh, document, and action-specific loading labels plus `aria-busy` state. |
| Async selection | A delayed generation response could appear under a different application selected while the request was running. | Document state is keyed to its application, stale reads are aborted, and late mutation responses update only their owning application. |
| Errors | Structured FastAPI validation details could render as `[object Object]`; network failures were vague. | Added readable field-level validation messages, API connection guidance, error styling, alert semantics, and dismissal. |
| Empty filters | A filtered list with zero results incorrectly showed first-run import instructions. | Added a distinct no-results state with one-click filter clearing and visible result counts. |
| Confirmation | Rejecting and marking an application submitted happened immediately. | Added native confirmation prompts with explicit consequences. “Mark as submitted” clarifies that the app does not submit externally. |
| Accessibility | No page language/title, skip link, focus treatment, select label, selected-row semantics, or progress-bar semantics. | Added document metadata, visible form labels, skip navigation, high-visibility focus, `aria-pressed`, live regions, named progress bars, screen-reader link context, and larger targets. |
| Dashboard clarity | Average match displayed `0%` before anything was analyzed and blocker copy implied analysis had run. | Empty metrics now use an em dash and pre-analysis content explicitly asks the user to analyze first. |
| Mobile layout | Important actions could become cramped, tracker scrolling hid content, and status/navigation context disappeared. | Removed the nested tracker scroll on narrow screens, stacked approval/actions, preserved navigation, and improved long-text wrapping down to 430 px. |
| Motion | Loading animation ignored reduced-motion preferences. | Spinner animation stops when the operating system requests reduced motion. |

## Functionality preserved

The work does not add job importing, profile editing, automated submission, document export,
authentication, or new API operations. It presents the existing API and workflow more clearly.
All original status guards and the explicit submission-approval requirement remain unchanged.

## Verification

- ESLint passed.
- React rules-of-hooks and effect dependency checks passed.
- TypeScript compilation passed.
- Vite production build passed.
- Output bundle: 208.88 kB JavaScript (65.40 kB gzip) and 11.57 kB CSS (3.48 kB gzip).

Visual browser automation could not run because the browser plugin's Node runtime was denied
access to the Windows user profile. Responsive and accessibility verification was therefore
limited to source/semantic review and the production compiler in this environment. A manual
keyboard and 390 px viewport smoke test remains recommended when a browser runtime is available.
