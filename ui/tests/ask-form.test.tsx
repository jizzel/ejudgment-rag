import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

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


it("an ended session sends the user to sign in again", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json({ error: { code: "unauthenticated", message: "expired" } }, { status: 401 }),
    ),
  );
  const { container } = render(<AskForm courts={null} />);
  fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "Who may evict?" } });
  fireEvent.submit(container.querySelector("form")!);
  await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/login?next=%2Fask"));
});
