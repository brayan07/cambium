import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  AlertTriangle,
} from "lucide-react";
import { useFsList, useFsFile, type FsRoot } from "../hooks/useFs";

interface FileBrowserProps {
  root: FsRoot;
  title: string;
}

/**
 * Read-only directory/file browser for a filesystem root exposed by the
 * server (memory or config). Directory tree on the left, file content on
 * the right. Deep-linkable via `?path=<relative path>`.
 */
export function FileBrowser({ root, title }: FileBrowserProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set([""]));
  const [selected, setSelected] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkedRef = useRef<string | null>(null);

  // Deep link: ?path=foo/bar.md selects the file and expands its ancestors.
  useEffect(() => {
    const path = searchParams.get("path");
    if (!path || deepLinkedRef.current === path) return;
    deepLinkedRef.current = path;
    setSelected(path);
    setExpanded((prev) => {
      const next = new Set(prev);
      next.add(""); // root always expanded
      const parts = path.split("/");
      for (let i = 1; i < parts.length; i++) {
        next.add(parts.slice(0, i).join("/"));
      }
      return next;
    });
  }, [searchParams]);

  const selectFile = (path: string) => {
    setSelected(path);
    setSearchParams({ path }, { replace: true });
  };

  const toggleDir = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center gap-3 border-b border-border px-6 py-3">
        <h1 className="font-display text-sm font-semibold text-text">
          {title}
        </h1>
        <span className="font-mono text-[10px] uppercase tracking-wide text-text-dim">
          /{root}
        </span>
        {selected && (
          <span className="truncate font-mono text-[10px] text-text-muted">
            {selected}
          </span>
        )}
      </div>

      <div className="flex min-h-0 flex-1">
        {/* Tree pane */}
        <div className="w-64 flex-shrink-0 overflow-y-auto border-r border-border py-2">
          <DirNode
            root={root}
            path=""
            name={`(${root})`}
            expanded={expanded}
            selected={selected}
            onToggle={toggleDir}
            onSelectFile={selectFile}
            depth={0}
          />
        </div>

        {/* Content pane */}
        <div className="min-w-0 flex-1 overflow-y-auto">
          {!selected && (
            <div className="flex h-full items-center justify-center text-sm text-text-dim">
              Select a file to view its contents.
            </div>
          )}
          {selected && <FileView root={root} path={selected} />}
        </div>
      </div>
    </div>
  );
}

// --- Tree ---

interface DirNodeProps {
  root: FsRoot;
  path: string;
  name: string;
  expanded: Set<string>;
  selected: string | null;
  onToggle: (path: string) => void;
  onSelectFile: (path: string) => void;
  depth: number;
}

function DirNode({
  root,
  path,
  name,
  expanded,
  selected,
  onToggle,
  onSelectFile,
  depth,
}: DirNodeProps) {
  const isOpen = expanded.has(path);
  const { data, isLoading, isError, error } = useFsList(root, path, isOpen);

  const sortedEntries = data?.entries
    ? [...data.entries].sort((a, b) => {
        // Dirs before files, then alphabetical.
        if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
        return a.name.localeCompare(b.name);
      })
    : [];

  return (
    <div>
      <button
        type="button"
        onClick={() => onToggle(path)}
        className="flex w-full items-center gap-1 px-2 py-1 text-left text-xs text-text hover:bg-surface-raised"
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        {isOpen ? (
          <ChevronDown className="h-3 w-3 flex-shrink-0 text-text-dim" />
        ) : (
          <ChevronRight className="h-3 w-3 flex-shrink-0 text-text-dim" />
        )}
        {isOpen ? (
          <FolderOpen className="h-3.5 w-3.5 flex-shrink-0 text-accent" />
        ) : (
          <Folder className="h-3.5 w-3.5 flex-shrink-0 text-accent" />
        )}
        <span className="truncate">{name}</span>
      </button>
      {isOpen && (
        <div>
          {isLoading && (
            <div
              className="px-2 py-1 text-[10px] text-text-dim"
              style={{ paddingLeft: `${(depth + 1) * 12 + 14}px` }}
            >
              Loading...
            </div>
          )}
          {isError && (
            <div
              className="px-2 py-1 text-[10px] text-status-failed"
              style={{ paddingLeft: `${(depth + 1) * 12 + 14}px` }}
            >
              {(error as Error)?.message ?? "Error"}
            </div>
          )}
          {!isLoading &&
            !isError &&
            sortedEntries.length === 0 && (
              <div
                className="px-2 py-1 text-[10px] italic text-text-dim"
                style={{ paddingLeft: `${(depth + 1) * 12 + 14}px` }}
              >
                (empty)
              </div>
            )}
          {sortedEntries.map((entry) => {
            const childPath = path ? `${path}/${entry.name}` : entry.name;
            if (entry.type === "dir") {
              return (
                <DirNode
                  key={childPath}
                  root={root}
                  path={childPath}
                  name={entry.name}
                  expanded={expanded}
                  selected={selected}
                  onToggle={onToggle}
                  onSelectFile={onSelectFile}
                  depth={depth + 1}
                />
              );
            }
            return (
              <FileEntry
                key={childPath}
                path={childPath}
                name={entry.name}
                size={entry.size}
                selected={selected === childPath}
                onSelect={onSelectFile}
                depth={depth + 1}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

function FileEntry({
  path,
  name,
  size,
  selected,
  onSelect,
  depth,
}: {
  path: string;
  name: string;
  size: number | null;
  selected: boolean;
  onSelect: (path: string) => void;
  depth: number;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(path)}
      className={`flex w-full items-center gap-1 py-1 pr-2 text-left text-xs transition-colors ${
        selected
          ? "bg-accent-dim text-accent"
          : "text-text-muted hover:bg-surface-raised hover:text-text"
      }`}
      style={{ paddingLeft: `${depth * 12 + 20}px` }}
      title={size !== null ? `${size} bytes` : undefined}
    >
      <FileText className="h-3.5 w-3.5 flex-shrink-0 text-text-dim" />
      <span className="truncate">{name}</span>
    </button>
  );
}

// --- Content ---

const MARKDOWN_EXTENSIONS = new Set([".md", ".markdown"]);

function FileView({ root, path }: { root: FsRoot; path: string }) {
  const { data, isLoading, isError, error } = useFsFile(root, path);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-text-dim">
        Loading...
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex h-full items-start gap-3 p-6 text-sm text-status-failed">
        <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
        <div>
          <div className="font-semibold">Could not read file</div>
          <div className="mt-1 text-xs">
            {(error as Error)?.message ?? "Unknown error"}
          </div>
          <a
            href={`/${root}/${path}`}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-block text-xs text-accent underline hover:text-accent-hover"
          >
            open raw →
          </a>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const isMarkdown = MARKDOWN_EXTENSIONS.has(data.extension);

  return (
    <div className="p-6">
      {isMarkdown ? (
        <div className="prose-cambium max-w-3xl">
          <Markdown remarkPlugins={[remarkGfm]}>{data.content}</Markdown>
        </div>
      ) : (
        <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded border border-border bg-surface p-4 font-mono text-xs text-text">
          {data.content}
        </pre>
      )}
      <div className="mt-4 font-mono text-[10px] text-text-dim">
        {data.size} bytes · last modified{" "}
        {new Date(data.modified * 1000).toLocaleString()}
      </div>
    </div>
  );
}
