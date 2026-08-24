import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import api, { type Extension, type User, type UserRole } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useState } from "react";

const roles: UserRole[] = ["SUPERADMIN", "MANAGER", "USER"];

export function AdminUsersPage() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    username: "",
    email: "",
    password: "",
    role: "USER" as UserRole,
    allowed_extensions: [] as string[],
  });

  const { data: users = [] } = useQuery({
    queryKey: ["users"],
    queryFn: async () => (await api.get<User[]>("/users")).data,
  });

  const { data: extensions = [] } = useQuery({
    queryKey: ["extensions"],
    queryFn: async () => (await api.get<Extension[]>("/admin/extensions")).data,
  });

  const createMutation = useMutation({
    mutationFn: async () => (await api.post("/users", form)).data,
    onSuccess: () => {
      setForm({ username: "", email: "", password: "", role: "USER", allowed_extensions: [] });
      void queryClient.invalidateQueries({ queryKey: ["users"] });
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: async (userId: number) => (await api.delete(`/users/${userId}`)).data,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  const toggleExtension = (extension: string) => {
    setForm((current) => ({
      ...current,
      allowed_extensions: current.allowed_extensions.includes(extension)
        ? current.allowed_extensions.filter((item) => item !== extension)
        : [...current.allowed_extensions, extension],
    }));
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">User Management</h1>
        <p className="text-muted-foreground">Create users and assign permitted MikoPBX extensions.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Create User</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>Username</Label>
              <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>Email</Label>
              <Input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>Password</Label>
              <Input
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Role</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value as UserRole })}
              >
                {roles.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-2">
            <Label>Allowed Extensions</Label>
            <div className="flex flex-wrap gap-2">
              {extensions.map((extension) => {
                const selected = form.allowed_extensions.includes(extension.extension);
                return (
                  <Button
                    key={extension.id}
                    type="button"
                    size="sm"
                    variant={selected ? "default" : "outline"}
                    onClick={() => toggleExtension(extension.extension)}
                  >
                    {extension.extension} {extension.display_name ? `· ${extension.display_name}` : ""}
                  </Button>
                );
              })}
              {!extensions.length && (
                <p className="text-sm text-muted-foreground">Sync PBX extensions first.</p>
              )}
            </div>
          </div>

          <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
            <Plus className="h-4 w-4" />
            Create user
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Existing Users</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Username</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Extensions</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((user) => (
                <TableRow key={user.id}>
                  <TableCell>{user.username}</TableCell>
                  <TableCell>{user.email}</TableCell>
                  <TableCell>{user.role}</TableCell>
                  <TableCell>{user.allowed_extensions.join(", ") || "-"}</TableCell>
                  <TableCell>{user.is_active ? "Active" : "Inactive"}</TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      disabled={!user.is_active || deactivateMutation.isPending}
                      onClick={() => deactivateMutation.mutate(user.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
