import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AskForm } from "@/components/AskForm";

afterEach(() => vi.unstubAllGlobals());

it("does not ask with a malformed year filter, and says why", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const { container } = render(<AskForm courts={null} />);
  fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "Who may evict?" } });
  fireEvent.change(screen.getByLabelText("To year"), { target: { value: "15" } });
  fireEvent.submit(container.querySelector("form")!);
  expect((await screen.findByRole("alert")).textContent).toContain(
    "One of the filters is not valid.",
  );
  expect(fetchMock).not.toHaveBeenCalled();
});
