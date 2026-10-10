import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { LoginForm } from "@/components/LoginForm";

it.each([
  ["invalid_credentials", "Email or password is incorrect."],
  ["too_many_attempts", "Too many failed sign-ins. Wait a few minutes and try again."],
  ["api_unreachable", "The research API is not running or not reachable."],
])("shows a clear message for %s and keeps the email", async (code, message) => {
  const action = vi.fn(async () => ({ error: code, email: "a@b.org" }));
  const { container } = render(<LoginForm action={action} next="/ask" />);
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@b.org" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "x" } });
  await act(async () => {
    fireEvent.submit(container.querySelector("form")!);
  });
  expect((await screen.findByRole("alert")).textContent).toBe(message);
  expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("a@b.org");
  const sent = action.mock.calls[0] as unknown as [unknown, FormData];
  expect(sent[1].get("next")).toBe("/ask");
});
