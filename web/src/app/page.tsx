"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/lib/auth";

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();

  return (
    <div className="flex flex-1 items-center justify-center px-4 py-16">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>LEASH</CardTitle>
          <CardDescription>
            Intent-aware purchase authority for AI shoppers — Hack Midwest 2026
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {loading ? (
            <p className="text-sm text-muted-foreground">Checking session…</p>
          ) : user ? (
            <>
              <p className="text-sm">
                Signed in as <span className="font-medium">{user.email}</span>
              </p>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Button
                  type="button"
                  onClick={() => router.push("/mission-control")}
                >
                  Open Mission Control
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => router.push("/profile")}
                >
                  Profile
                </Button>
              </div>
            </>
          ) : (
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button type="button" onClick={() => router.push("/signin")}>
                Sign in
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => router.push("/signup")}
              >
                Sign up
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
