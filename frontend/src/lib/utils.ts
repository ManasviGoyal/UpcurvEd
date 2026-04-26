// frontend/src/lib/utils.ts

// Minimal version (no extra deps):
export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

// If you prefer the "shadcn" version later, install deps and use:
//
// import { type ClassValue, clsx } from "clsx";
// import { twMerge } from "tailwind-merge";
// export function cn(...inputs: ClassValue[]) {
//   return twMerge(clsx(inputs));
// }
