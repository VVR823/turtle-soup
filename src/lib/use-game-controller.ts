'use client';

import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { GameController, type GameState } from './game-controller';
import type { GameTarget } from './game-journal';

const serverSnapshot: GameState = { phase: 'initializing', session: null, pending: null, error: null };

export function useGameController({ soupId, level }: GameTarget) {
  const controller = useMemo(() => new GameController({ soupId, level }), [soupId, level]);
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot, () => serverSnapshot);
  useEffect(() => {
    void controller.initialize();
    return () => controller.dispose();
  }, [controller]);
  return { state, controller };
}
