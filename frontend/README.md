# ExamRAG Frontend

React + TypeScript app built with Vite, using TanStack Query for server state.

## Layout

```text
src/
├── main.tsx          # React root
├── App.tsx           # QueryClientProvider and page composition
├── index.css         # Global styles
├── pages/            # Screen-level components
├── components/       # Reusable UI pieces
└── services/api.ts   # Typed backend calls and the API base URL
```

Upload, MCQ and FAQ screens are added in the phases that implement them.

## Local development

```bash
npm install
npm run dev      # http://localhost:3000
```

The backend URL comes from `VITE_API_BASE_URL` and defaults to
`http://localhost:8000`.

## Checks

```bash
npm run lint     # tsc --noEmit
npm run build
```
