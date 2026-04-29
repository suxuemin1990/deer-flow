import { WorkflowHubTree } from "./_components/workflow-hub-tree";

export default function WorkflowsHubPage() {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-4">
        <h1 className="text-lg font-semibold">Workflows</h1>
        <p className="text-muted-foreground text-sm">
          All workflows you&apos;ve started, grouped by chat.
        </p>
      </div>
      <div className="flex-1 overflow-auto">
        <WorkflowHubTree />
      </div>
    </div>
  );
}
