import { WorkflowHubTree } from "./_components/workflow-hub-tree";

export default function WorkflowsHubPage() {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-4">
        <h1 className="text-lg font-semibold">工作流</h1>
        <p className="text-muted-foreground text-sm">
          你启动过的所有工作流，按对话分组。
        </p>
      </div>
      <div className="flex-1 overflow-auto">
        <WorkflowHubTree />
      </div>
    </div>
  );
}
