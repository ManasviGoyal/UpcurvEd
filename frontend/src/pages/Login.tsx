import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import type { User } from "@/types";
import { getFirebaseAuth, getGoogleProvider } from "@/firebase";
import { signInWithPopup, signInWithEmailAndPassword, createUserWithEmailAndPassword } from "firebase/auth";
import { z } from "zod";
import { isDesktopLocalMode } from "@/lib/runtime";

interface LoginPageProps {
  setView: (view: string) => void;
  setUser: (user: User) => void;
  users: User[];
  setUsers: (users: User[]) => void;
}

const emailSchema = z.string().email("Please enter a valid email address");

const passwordSchema = z.string()
  .min(8, "Password must be at least 8 characters")
  .regex(/[A-Z]/, "Password must contain at least 1 uppercase letter")
  .regex(/[a-z]/, "Password must contain at least 1 lowercase letter")
  .regex(/[^A-Za-z0-9]/, "Password must contain at least 1 special character");

export const LoginPage = ({ setView, setUser, users, setUsers }: LoginPageProps) => {
  const desktopLocal = isDesktopLocalMode();
  const [isLogin, setIsLogin] = useState(true);
  const [error, setError] = useState('');
  const [formData, setFormData] = useState({ name: '', email: '', password: '', confirmPassword: '' });

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    setError('');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    // Validate email
    const emailValidation = emailSchema.safeParse(formData.email);
    if (!emailValidation.success) {
      setError(emailValidation.error.errors[0].message);
      return;
    }

    if (desktopLocal) {
      const email = formData.email.trim().toLowerCase();
      const fallbackName = email.split("@")[0] || "User";
      const name = (formData.name || "").trim() || fallbackName;
      const existing = users.find((u) => u.email === email);
      const userObj: User = existing
        ? { ...existing, name }
        : {
            name,
            email,
            chats: [],
          };
      if (!existing) setUsers([...users, userObj]);
      try {
        localStorage.setItem(
          "app.localUser",
          JSON.stringify({
            name: userObj.name,
            email: userObj.email,
          })
        );
      } catch {}
      setUser(userObj);
      setView("chat");
      return;
    }

    const auth = getFirebaseAuth();

    // Validate password for signup (frontend policy; Firebase requires min 6 only)
    if (!isLogin) {
      const passwordValidation = passwordSchema.safeParse(formData.password);
      if (!passwordValidation.success) {
        setError(passwordValidation.error.errors[0].message);
        return;
      }
      if (formData.password !== formData.confirmPassword) {
        setError('Passwords do not match');
        return;
      }
    }

    try {
      if (isLogin) {
        const cred = await signInWithEmailAndPassword(auth, formData.email, formData.password);
        const fbUser = cred.user;
        const idToken = await fbUser.getIdToken();
        const email = fbUser.email || formData.email;
        const existing = users.find(u => u.email === email);
        let userObj: User;
        if (existing) {
          userObj = { ...existing, uid: fbUser.uid, idToken };
        } else {
          userObj = {
            name: fbUser.displayName || formData.name || email.split('@')[0] || "User",
            email,
            uid: fbUser.uid,
            idToken,
            chats: [], // No initial chat; create on first prompt/generation
          };
          setUsers([...users, userObj]);
        }
  setUser(userObj);
  setView('chat');
      } else {
        const cred = await createUserWithEmailAndPassword(auth, formData.email, formData.password);
        const fbUser = cred.user;
        const idToken = await fbUser.getIdToken();
        const email = fbUser.email || formData.email;
        const existing = users.find(u => u.email === email);
        let userObj: User;
        if (existing) {
          userObj = { ...existing, name: formData.name || existing.name, uid: fbUser.uid, idToken };
        } else {
          userObj = {
            name: formData.name || email.split('@')[0] || "User",
            email,
            uid: fbUser.uid,
            idToken,
            chats: [],
          };
          setUsers([...users, userObj]);
        }
  setUser(userObj);
  setView('chat');
      }
    } catch (err: any) {
      const code = err?.code as string | undefined;
      const msg =
        code === 'auth/invalid-email' ? 'Invalid email address.' :
        code === 'auth/invalid-credential' ? 'Incorrect email or password.' :
        code === 'auth/user-not-found' ? 'No account found with this email.' :
        code === 'auth/wrong-password' ? 'Incorrect password.' :
        code === 'auth/email-already-in-use' ? 'An account with this email already exists.' :
        code === 'auth/weak-password' ? 'Password is too weak.' :
        err?.message || 'Authentication failed';
      setError(msg);
    }
  };

  const handleGoogleSignIn = async () => {
    if (desktopLocal) {
      setError("Google sign-in is disabled in desktop local mode. Continue with email.");
      return;
    }
    try {
      const auth = getFirebaseAuth();
      const provider = getGoogleProvider();
      const result = await signInWithPopup(auth, provider);
      const firebaseUser = result.user;
      const idToken = await firebaseUser.getIdToken();
      // If user exists locally keep chats, else initialize
      const existing = users.find(u => u.email === firebaseUser.email);
      let userObj: User;
      if (existing) {
        userObj = { ...existing, uid: firebaseUser.uid, idToken };
      } else {
        userObj = {
          name: firebaseUser.displayName || firebaseUser.email?.split('@')[0] || "User",
          email: firebaseUser.email || "unknown@example.com",
          uid: firebaseUser.uid,
          idToken,
          chats: [], // No initial chat; create on first prompt/generation
        };
        setUsers([...users, userObj]);
      }
  setUser(userObj);
  setView('chat');
    } catch (e: any) {
      const code = e?.code as string | undefined;
      const msg = code?.startsWith('auth/') ? 'Google sign-in failed. Please try again.' : (e?.message || 'Google sign-in failed');
      setError(msg);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-secondary">
      <Card className="w-full max-w-sm p-8">
        <h2 className="text-2xl font-bold text-center mb-6">
          {desktopLocal ? "Continue Locally" : (isLogin ? 'Welcome Back' : 'Create Account')}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          {(!isLogin || desktopLocal) && (
            <div>
              <label className="text-sm font-medium">Name</label>
              <Input
                name="name"
                type="text"
                placeholder="Your Name"
                value={formData.name}
                onChange={handleInputChange}
                required={desktopLocal || !isLogin}
              />
            </div>
          )}
          <div>
            <label className="text-sm font-medium">Email</label>
            <Input
              name="email"
              type="email"
              placeholder="user@example.com"
              value={formData.email}
              onChange={handleInputChange}
              required
            />
          </div>
          {!desktopLocal && (
            <div>
              <label className="text-sm font-medium">Password</label>
              <Input
                name="password"
                type="password"
                placeholder="••••••••"
                value={formData.password}
                onChange={handleInputChange}
                required
              />
            </div>
          )}
          {!desktopLocal && !isLogin && (
            <div>
              <label className="text-sm font-medium">Confirm Password</label>
              <Input
                name="confirmPassword"
                type="password"
                placeholder="••••••••"
                value={formData.confirmPassword}
                onChange={handleInputChange}
                required
              />
            </div>
          )}
          {error && <p className="text-sm text-red-500">{error}</p>}
          <Button type="submit" className="w-full">
            {desktopLocal ? "Continue" : (isLogin ? 'Sign In' : 'Sign Up')}
          </Button>
          {!desktopLocal && (
            <>
              <div className="relative my-4 text-center">
                <div className="absolute inset-0 flex items-center">
                  <span className="w-full border-t border-border" />
                </div>
                <div className="relative flex justify-center text-xs uppercase">
                  <span className="bg-card px-2 text-muted-foreground">or</span>
                </div>
              </div>
              <Button type="button" variant="outline" onClick={handleGoogleSignIn} className="w-full flex items-center justify-center gap-2 py-2 font-medium">
                <GoogleIcon />
                <span>Sign in with Google</span>
              </Button>
            </>
          )}
        </form>
        {!desktopLocal && (
          <p className="text-center text-sm text-muted-foreground mt-6">
            {isLogin ? "Don't have an account?" : "Already have an account?"}
            <button
              onClick={() => { setIsLogin(!isLogin); setError(''); }}
              className="font-semibold text-primary hover:underline ml-1"
            >
              {isLogin ? 'Sign Up' : 'Sign In'}
            </button>
          </p>
        )}
      </Card>
    </div>
  );
};

// Official multicolor Google "G" logo (SVG) per brand guidelines (do not modify colors)
const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#EA4335" d="M24 9.5c3.54 0 6.72 1.22 9.22 3.22l6.85-6.85C35.9 2.38 30.3 0 24 0 14.62 0 6.4 5.38 2.54 13.22l7.96 6.19C12.43 13.05 17.74 9.5 24 9.5z"/>
    <path fill="#4285F4" d="M46.08 24.62c0-1.54-.14-3.02-.4-4.44H24v8.48h12.44c-.54 2.74-2.17 5.06-4.49 6.62l7.04 5.46c4.12-3.8 6.49-9.4 6.49-16.12z"/>
    <path fill="#FBBC05" d="M10.5 28.59A14.5 14.5 0 0 1 9.5 24c0-1.59.28-3.13.78-4.59l-7.96-6.19A24.04 24.04 0 0 0 0 24c0 3.87.92 7.52 2.54 10.78l7.96-6.19z"/>
    <path fill="#34A853" d="M24 48c6.3 0 11.6-2.07 15.47-5.63l-7.04-5.46c-2.07 1.38-4.73 2.19-8.43 2.19-6.26 0-11.57-3.55-14.5-8.69l-7.96 6.19C6.4 42.62 14.62 48 24 48z"/>
    <path fill="none" d="M0 0h48v48H0z"/>
  </svg>
);
