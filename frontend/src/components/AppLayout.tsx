import { Link, NavLink, Outlet } from "react-router-dom";
import { Headphones, LogOut, Moon, PhoneCall, Settings, Sun, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/calls", label: "Call Records", icon: PhoneCall },
  { to: "/admin/pbx", label: "PBX Settings", icon: Settings, roles: ["SUPERADMIN"] },
  { to: "/admin/users", label: "Users", icon: Users, roles: ["SUPERADMIN"] },
];

export function AppLayout() {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex min-h-screen max-w-7xl">
        <aside className="hidden w-64 flex-col border-r bg-card/40 p-6 md:flex">
          <Link to="/calls" className="mb-8 flex items-center gap-2 text-lg font-semibold">
            <Headphones className="h-6 w-6 text-primary" />
            Whisper
          </Link>
          <nav className="space-y-1">
            {navItems
              .filter((item) => !item.roles || (user && item.roles.includes(user.role)))
              .map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                      isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted"
                    )
                  }
                >
                  <item.icon className="h-4 w-4" />
                  {item.label}
                </NavLink>
              ))}
          </nav>
          <div className="mt-auto space-y-3">
            <div className="rounded-lg border p-3 text-sm">
              <div className="font-medium">{user?.username}</div>
              <div className="text-muted-foreground">{user?.role}</div>
            </div>
            <Button variant="outline" className="w-full" onClick={toggleTheme}>
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              Toggle theme
            </Button>
            <Button variant="ghost" className="w-full justify-start" onClick={logout}>
              <LogOut className="h-4 w-4" />
              Sign out
            </Button>
          </div>
        </aside>
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
