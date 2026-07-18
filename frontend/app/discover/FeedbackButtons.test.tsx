import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import FeedbackButtons from "./FeedbackButtons";

describe("FeedbackButtons", () => {
  it("posts the verdict and disables after click", async () => {
    const onFeedback = vi.fn().mockResolvedValue(undefined);
    render(<FeedbackButtons trackId="t1" onFeedback={onFeedback} />);
    await userEvent.click(screen.getByRole("button", { name: "👍" }));
    expect(onFeedback).toHaveBeenCalledWith("t1", "up");
    expect(
      (screen.getByRole("button", { name: "👍" }) as HTMLButtonElement).disabled
    ).toBe(true);
  });

  it("offers all three verdicts", () => {
    render(<FeedbackButtons trackId="t1" onFeedback={vi.fn()} />);
    for (const label of ["👍", "👎", "More like this"]) {
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
  });
});
