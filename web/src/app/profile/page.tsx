"use client";

import { useEffect } from "react";
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

export default function ProfilePage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/signin");
    }
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <div className="flex flex-1 items-center justify-center px-4 py-16">
        <p className="text-sm text-muted-foreground">
          {loading ? "Loading profile…" : "Redirecting to sign in…"}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-1 items-center justify-center px-4 py-16">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>Your account details</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid gap-3 text-sm">
            <div className="grid gap-1">
              <dt className="text-muted-foreground">Email</dt>
              <dd className="font-medium">{user.email}</dd>
            </div>
            <div className="grid gap-1">
              <dt className="text-muted-foreground">User ID</dt>
              <dd className="break-all font-mono text-xs">{user.id}</dd>
            </div>
          </dl>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              logout();
              router.push("/");
            }}
          >
            Sign out
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
