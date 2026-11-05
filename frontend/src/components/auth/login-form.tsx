"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle, Eye, EyeOff, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";
import { signIn, workspacePath } from "@/lib/auth";
import { hardNavigate } from "@/lib/navigation";
import { loginSchema, type LoginValues } from "@/lib/validations/auth";

// Brand-blue focus indicator; the default grey ring is too faint on white.
// Invalid fields keep the red error styling while focused.
const focusRing =
  "focus-visible:border-blue-600 focus-visible:ring-blue-600/20 aria-invalid:focus-visible:border-destructive aria-invalid:focus-visible:ring-destructive/20";

// Codes whose backend message is written for end users.
const USER_FACING_CODES = new Set([
  "invalid_credentials",
  "account_inactive",
  "rate_limited",
  "service_unavailable",
  "network_error",
  // Company sign-in refused by the subscription (stable backend codes).
  "subscription_expired",
  "subscription_not_started",
  "subscription_not_configured",
]);

function loginErrorMessage(error: unknown): string {
  if (error instanceof ApiError && USER_FACING_CODES.has(error.code)) {
    return error.message;
  }
  if (error instanceof ApiError && error.code === "validation_error") {
    return "Check your email address and password, then try again.";
  }
  return "We could not sign you in. Please try again.";
}

export function LoginForm() {
  const [showPassword, setShowPassword] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  // Keeps the button in its loading state while the workspace page loads.
  const [redirecting, setRedirecting] = useState(false);
  // Synchronous guard: a second Enter/click can arrive before React re-renders.
  const inFlight = useRef(false);

  const {
    register,
    handleSubmit,
    resetField,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  /** Return the form to a fresh, usable state and drop the typed password. */
  const resetTransientState = useCallback(() => {
    inFlight.current = false;
    setRedirecting(false);
    setShowPassword(false);
    resetField("password");
  }, [resetField]);

  // If this form is ever hidden by <Activity> or restored from the browser's
  // back/forward cache, it must not come back stuck or holding a password.
  useLayoutEffect(() => resetTransientState, [resetTransientState]);
  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) resetTransientState();
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [resetTransientState]);

  async function onSubmit(values: LoginValues) {
    if (inFlight.current) return;
    inFlight.current = true;
    setFormError(null);
    try {
      const user = await signIn(values);
      setRedirecting(true);
      // Full page load so no client-side state survives the identity change.
      hardNavigate(workspacePath(user));
    } catch (error) {
      inFlight.current = false;
      setFormError(loginErrorMessage(error));
    }
  }

  const busy = isSubmitting || redirecting;

  return (
    <form
      // If the user submits before JavaScript has loaded, the browser falls back
      // to a native submission: POST keeps credentials out of the URL, history
      // and access logs (the default GET would put them in the query string).
      method="post"
      onSubmit={(event) => void handleSubmit(onSubmit)(event)}
      noValidate
      className="space-y-6"
      aria-label="Sign in"
    >
      {formError && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <p>{formError}</p>
        </div>
      )}

      <div className="space-y-2">
        <Label htmlFor="email" className="text-sm font-medium text-slate-700">
          Email Address
        </Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          inputMode="email"
          placeholder="name@company.com"
          aria-invalid={errors.email ? true : undefined}
          aria-describedby={errors.email ? "email-error" : undefined}
          className={`h-11 rounded-lg bg-white px-3.5 text-slate-900 shadow-xs ${focusRing}`}
          {...register("email")}
        />
        {errors.email && (
          <p id="email-error" role="alert" className="text-sm text-destructive">
            {errors.email.message}
          </p>
        )}
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="password" className="text-sm font-medium text-slate-700">
            Password
          </Label>
          {/* Not a link until the password recovery module exists, so it can never 404. */}
          <span
            title="Password recovery is not available yet"
            className="cursor-default text-sm font-medium text-blue-700"
          >
            Forgot password?
            <span className="sr-only"> (not available yet)</span>
          </span>
        </div>
        <div className="relative">
          <Input
            id="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            placeholder="Enter your password"
            aria-invalid={errors.password ? true : undefined}
            aria-describedby={errors.password ? "password-error" : undefined}
            className={`h-11 rounded-lg bg-white px-3.5 pr-11 text-slate-900 shadow-xs ${focusRing}`}
            {...register("password")}
          />
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            aria-label={showPassword ? "Hide password" : "Show password"}
            aria-pressed={showPassword}
            className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-lg text-slate-500 transition-colors hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/50"
          >
            {showPassword ? (
              <EyeOff className="size-4" aria-hidden="true" />
            ) : (
              <Eye className="size-4" aria-hidden="true" />
            )}
          </button>
        </div>
        {errors.password && (
          <p id="password-error" role="alert" className="text-sm text-destructive">
            {errors.password.message}
          </p>
        )}
      </div>

      <Button
        type="submit"
        disabled={busy}
        className="h-11 w-full rounded-lg bg-gradient-to-r from-[#0b1a3d] to-[#1b4fc4] text-base font-medium text-white shadow-md transition-all hover:from-[#0f2352] hover:to-[#2260e0] hover:shadow-lg focus-visible:ring-3 focus-visible:ring-blue-600/40 focus-visible:ring-offset-2"
      >
        {busy ? (
          <>
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            Signing in…
          </>
        ) : (
          "Sign In"
        )}
      </Button>
    </form>
  );
}
