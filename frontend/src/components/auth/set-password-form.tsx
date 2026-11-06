"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Eye, EyeOff, Loader2 } from "lucide-react";

import { ErrorAlert, Field, INPUT_CLASS, PRIMARY_BUTTON } from "@/components/company/ui-kit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";

const MIN_LENGTH = 12;

type LinkInfo = { full_name: string; email: string; expires_at: string };

/** Reads the token from the URL fragment (never sent to servers) and removes it from the address bar. */
export function readTokenFromHash(hash: string): string | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const token = params.get("token");
  return token && token.length <= 200 ? token : null;
}

export function passwordProblem(password: string, confirm: string): string | null {
  if (password.length < MIN_LENGTH) return `Use at least ${MIN_LENGTH} characters.`;
  if (password.length > 128) return "Use at most 128 characters.";
  if (password.trim() !== password) return "The password must not start or end with a space.";
  if (new Set(password).size < 5) return "The password is too repetitive.";
  if (password !== confirm) return "The passwords do not match.";
  return null;
}

export function SetPasswordForm() {
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState<"checking" | "ready" | "invalid" | "done">("checking");
  const [info, setInfo] = useState<LinkInfo | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const inFlight = useRef(false);

  useEffect(() => {
    const found = readTokenFromHash(window.location.hash);
    // Drop the token from the address bar and history straight away.
    window.history.replaceState(null, "", window.location.pathname);
    void (async () => {
      await Promise.resolve(); // state updates happen after the effect, not inside it
      if (!found) {
        setState("invalid");
        return;
      }
      setToken(found);
      try {
        const data = await apiFetch<LinkInfo>("/auth/password-setup/check", {
          method: "POST",
          body: JSON.stringify({ token: found }),
        });
        setInfo(data);
        setState("ready");
      } catch (e) {
        setServerError(e instanceof ApiError ? e.message : null);
        setState("invalid");
      }
    })();
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!token || inFlight.current) return;
    const issue = passwordProblem(password, confirm);
    setProblem(issue);
    if (issue) return;
    inFlight.current = true;
    setSaving(true);
    setServerError(null);
    try {
      await apiFetch<void>("/auth/password-setup", {
        method: "POST",
        body: JSON.stringify({ token, password }),
      });
      setPassword("");
      setConfirm("");
      setState("done");
    } catch (error) {
      const err = error instanceof ApiError ? error : null;
      if (err?.code === "invalid_setup_link") setState("invalid");
      setServerError(err?.message ?? "Your password could not be set. Please try again.");
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  if (state === "checking") {
    return (
      <p className="flex items-center gap-2 text-sm text-slate-600" role="status">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        Checking your link…
      </p>
    );
  }
  if (state === "invalid") {
    return (
      <div className="space-y-4">
        <ErrorAlert>
          {serverError ??
            "This setup link is invalid, expired or already used. Ask your Company Admin for a new link."}
        </ErrorAlert>
        <Link href="/login" className="text-sm font-medium text-blue-700 hover:underline">
          Go to sign in
        </Link>
      </div>
    );
  }
  if (state === "done") {
    return (
      <div className="space-y-4" role="status">
        <p className="flex items-start gap-2 text-sm text-emerald-900">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden="true" />
          Your password is set. You can now sign in with your email address.
        </p>
        <Link href="/login" className={`${PRIMARY_BUTTON} inline-flex items-center rounded-lg px-4 text-sm font-medium`}>
          Sign in
        </Link>
      </div>
    );
  }

  return (
    <form noValidate onSubmit={submit} className="space-y-4" aria-label="Set your password">
      {info && (
        <p className="text-sm text-slate-600">
          Setting the password for <strong className="text-slate-900">{info.full_name}</strong> (
          {info.email}). This link is valid until {formatDateTime(info.expires_at)} PKT.
        </p>
      )}
      {serverError && <ErrorAlert>{serverError}</ErrorAlert>}
      <Field id="new-password" label="New password" hint={`At least ${MIN_LENGTH} characters.`}>
        <div className="relative">
          <Input
            id="new-password"
            type={show ? "text" : "password"}
            className={`${INPUT_CLASS} pr-11`}
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              setProblem(null);
            }}
            autoComplete="new-password"
            aria-describedby="new-password-hint"
            maxLength={128}
          />
          <button
            type="button"
            onClick={() => setShow((v) => !v)}
            aria-label={show ? "Hide password" : "Show password"}
            aria-pressed={show}
            className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-slate-500 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/40"
          >
            {show ? <EyeOff className="size-4" aria-hidden="true" /> : <Eye className="size-4" aria-hidden="true" />}
          </button>
        </div>
      </Field>
      <Field id="confirm-password" label="Confirm password" error={problem}>
        <Input
          id="confirm-password"
          type={show ? "text" : "password"}
          className={INPUT_CLASS}
          value={confirm}
          onChange={(e) => {
            setConfirm(e.target.value);
            setProblem(null);
          }}
          autoComplete="new-password"
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? "confirm-password-error" : undefined}
          maxLength={128}
        />
      </Field>
      <Button type="submit" disabled={saving} className={`${PRIMARY_BUTTON} w-full`}>
        {saving && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
        {saving ? "Saving…" : "Set password"}
      </Button>
    </form>
  );
}
