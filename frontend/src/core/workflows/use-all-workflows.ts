import { useQuery } from "@tanstack/react-query";

import { fetchAllWorkflows } from "./api";
import type { AllWorkflowsResponse } from "./types";

const HUB_REFRESH_MS = 3_000;

export function useAllWorkflows() {
  return useQuery<AllWorkflowsResponse>({
    queryKey: ["workflows", "all"],
    queryFn: ({ signal }) => fetchAllWorkflows(signal),
    refetchInterval: HUB_REFRESH_MS,
    refetchIntervalInBackground: false,
  });
}
