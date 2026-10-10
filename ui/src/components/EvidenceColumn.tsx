"use client";

import { useEffect, useRef } from "react";

import { useNarrow } from "@/lib/media";
import type { PassageContext } from "@/lib/types";

import { ErrorPanel } from "./ErrorPanel";
import { EvidencePanel, type Mark } from "./EvidencePanel";
import { quietButton, textLink } from "./ui";

export type Evidence =
  | { kind: "none" }
  | { kind: "loading"; chunkId: string }
  | { kind: "shown"; chunkId: string; context: PassageContext }
  | { kind: "error"; chunkId: string; code: string; message: string };

/**
 * The right-hand column of a workspace: a sticky panel beside the results on large screens. On
 * small screens it is a full-screen modal <dialog> (showModal): focus moves into it, the page
 * behind is inert, Escape closes it, and the workspace returns focus to the opening link.
 */
export function EvidenceColumn({
  evidence,
  mark,
  pageHref,
  onClose,
  empty,
  backLabel = "← Back to results",
}: {
  evidence: Evidence;
  mark: Mark;
  pageHref: string | null;
  onClose: () => void;
  empty: string;
  backLabel?: string;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const sheet = useRef<HTMLDialogElement>(null);
  const narrow = useNarrow();
  const selected = evidence.kind === "none" ? null : evidence.chunkId;
  const open = selected !== null;

  useEffect(() => {
    panel.current?.scrollTo?.({ top: 0 });
    sheet.current?.scrollTo?.({ top: 0 });
  }, [selected]);

  useEffect(() => {
    const dialog = sheet.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, [open, narrow]);

  useEffect(() => {
    if (!open || narrow) return; // the modal sheet handles Escape itself (its cancel event)
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, narrow, onClose]);

  const toolbar = (
    <div className="sticky top-0 z-10 -mx-4 flex items-center justify-between gap-2 border-b border-line bg-surface px-4 py-2 lg:static lg:mx-0 lg:border-0 lg:p-0">
      <button type="button" onClick={onClose} className={`${quietButton} lg:hidden`}>
        {backLabel}
      </button>
      <span className="hidden text-xs font-medium tracking-wide text-muted uppercase lg:inline">In context</span>
      <span className="flex items-center gap-3 text-sm">
        {pageHref && (
          <a href={pageHref} className={textLink}>
            Open as a page
          </a>
        )}
        <span className="hidden lg:inline">
          <button type="button" onClick={onClose} aria-label="Close the passage" className={quietButton}>
            ✕
          </button>
        </span>
      </span>
    </div>
  );

  // One toolbar for every state, so the control that has focus (the sheet focuses its first
  // one on opening) is not replaced when the passage arrives.
  const content = open && (
    <div className="space-y-4">
      {toolbar}
      {evidence.kind === "loading" && (
        <p aria-busy="true" className="text-sm text-muted">
          Loading the passage…
        </p>
      )}
      {evidence.kind === "error" && <ErrorPanel code={evidence.code} detail={evidence.message} />}
      {evidence.kind === "shown" && <EvidencePanel context={evidence.context} mark={mark} />}
    </div>
  );

  if (narrow) {
    if (!open) return null;
    return (
      <dialog
        ref={sheet}
        aria-label="Passage in context"
        onCancel={(event) => {
          event.preventDefault(); // close through the workspace, which restores the list
          onClose();
        }}
        className="m-0 h-full max-h-none w-full max-w-none overflow-y-auto bg-surface px-4 pb-6 text-ink backdrop:bg-black/40"
      >
        {content}
      </dialog>
    );
  }

  return (
    <div
      ref={panel}
      role={open ? "region" : undefined}
      aria-label={open ? "Passage in context" : undefined}
      className={
        open
          ? "hidden max-h-[calc(100vh-2rem)] overflow-y-auto rounded-lg border border-line bg-surface p-5 lg:sticky lg:top-4 lg:block lg:self-start"
          : "hidden lg:block"
      }
    >
      {evidence.kind === "none" && (
        <p className="sticky top-4 rounded-lg border border-dashed border-line p-5 text-sm text-muted">{empty}</p>
      )}
      {content}
    </div>
  );
}
