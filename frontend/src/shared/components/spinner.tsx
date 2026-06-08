import { Loader2 } from "@/shared/images"
import { cn } from "@/shared/utils/utils"

export const Spinner = ({ className }: { className?: string }) => {
  return <Loader2 className={cn("h-4 w-4 animate-spin", className)} />
}

