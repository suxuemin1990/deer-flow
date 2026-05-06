"use client";

import { useMemo } from "react";
import type {
  AnchorHTMLAttributes,
  ImgHTMLAttributes,
} from "react";

import {
  MessageResponse,
  type MessageResponseProps,
} from "@/components/ai-elements/message";
import { resolveArtifactURL } from "@/core/artifacts/utils";
import { streamdownPlugins } from "@/core/streamdown";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";

function isExternalUrl(href: string | undefined): boolean {
  return !!href && /^https?:\/\//.test(href);
}

/** Rewrite absolute host paths under the thread's user-data dir to the
 * backend artifacts endpoint. Mirrors the logic in `MessageImage` and the
 * anchor override in `message-list-item.tsx`. */
function maybeResolveArtifactPath(
  url: string | undefined,
  threadId: string | undefined,
): string | undefined {
  if (!url || !threadId) return url;
  if (url.includes("/user-data/")) {
    return resolveArtifactURL(url, threadId);
  }
  return url;
}

export type MarkdownContentProps = {
  content: string;
  isLoading: boolean;
  rehypePlugins: MessageResponseProps["rehypePlugins"];
  className?: string;
  remarkPlugins?: MessageResponseProps["remarkPlugins"];
  components?: MessageResponseProps["components"];
  /** Optional thread id used to resolve in-content artifact URLs. When
   * provided, ``<img src>`` and ``<a href>`` values that point under
   * ``/user-data/`` are rewritten to the backend artifacts endpoint. */
  threadId?: string;
};

/** Renders markdown content. */
export function MarkdownContent({
  content,
  rehypePlugins,
  className,
  remarkPlugins = streamdownPlugins.remarkPlugins,
  components: componentsFromProps,
  threadId,
}: MarkdownContentProps) {
  const components = useMemo(() => {
    return {
      // Replace Streamdown's default image renderer (which wraps the <img>
      // in a hover-overlay <div>) with a plain <img>. The wrapper div
      // breaks HTML nesting rules when the image appears inline inside a
      // <p>, producing a React hydration warning.
      img: ({ src, alt, ...rest }: ImgHTMLAttributes<HTMLImageElement>) => {
        const resolved = typeof src === "string"
          ? maybeResolveArtifactPath(src, threadId)
          : src;
        return <img src={resolved} alt={alt} {...rest} />;
      },
      a: (props: AnchorHTMLAttributes<HTMLAnchorElement>) => {
        if (typeof props.children === "string") {
          const match = /^citation:(.+)$/.exec(props.children);
          if (match) {
            const [, text] = match;
            return <CitationLink {...props}>{text}</CitationLink>;
          }
        }
        const { className, target, rel, href, ...rest } = props;
        const resolvedHref = maybeResolveArtifactPath(href, threadId);
        const external = isExternalUrl(resolvedHref);
        return (
          <a
            {...rest}
            href={resolvedHref}
            className={cn(
              "text-primary decoration-primary/30 hover:decoration-primary/60 underline underline-offset-2 transition-colors",
              className,
            )}
            target={target ?? (external ? "_blank" : undefined)}
            rel={rel ?? (external ? "noopener noreferrer" : undefined)}
          />
        );
      },
      ...componentsFromProps,
    };
  }, [componentsFromProps, threadId]);

  if (!content) return null;

  return (
    <MessageResponse
      className={className}
      remarkPlugins={remarkPlugins}
      rehypePlugins={rehypePlugins}
      components={components}
    >
      {content}
    </MessageResponse>
  );
}
