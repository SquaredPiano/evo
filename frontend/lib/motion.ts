export const springTransition = { type: "spring" as const, stiffness: 300, damping: 28, mass: 0.8 };
export const smoothTransition = {
  duration: 0.35,
  ease: [0.16, 1, 0.3, 1] as [number, number, number, number],
};
