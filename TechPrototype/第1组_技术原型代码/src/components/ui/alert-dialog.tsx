"use client"

import * as React from "react"
import { AlertDialog as AlertDialogPrimitive } from "radix-ui"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

const AlertDialog = AlertDialogPrimitive.Root
const AlertDialogTrigger = AlertDialogPrimitive.Trigger

function AlertDialogContent({ className, ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Content>) {
  return (
    <AlertDialogPrimitive.Portal>
      <AlertDialogPrimitive.Overlay className="fixed inset-0 z-[70] bg-black/35 backdrop-blur-[1px] data-open:animate-in data-open:fade-in-0 motion-reduce:animate-none" />
      <AlertDialogPrimitive.Content
        className={cn("fixed left-1/2 top-1/2 z-[71] grid w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 gap-4 rounded-xl border bg-popover p-5 shadow-xl data-open:animate-in data-open:zoom-in-95 motion-reduce:animate-none", className)}
        {...props}
      />
    </AlertDialogPrimitive.Portal>
  )
}

function AlertDialogHeader(props: React.ComponentProps<"div">) { return <div className="grid gap-2" {...props} /> }
function AlertDialogFooter({ className, ...props }: React.ComponentProps<"div">) { return <div className={cn("flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)} {...props} /> }
function AlertDialogTitle(props: React.ComponentProps<typeof AlertDialogPrimitive.Title>) { return <AlertDialogPrimitive.Title className="text-base font-semibold" {...props} /> }
function AlertDialogDescription(props: React.ComponentProps<typeof AlertDialogPrimitive.Description>) { return <AlertDialogPrimitive.Description className="text-sm leading-6 text-muted-foreground" {...props} /> }

function AlertDialogCancelButton(props: React.ComponentProps<typeof Button>) {
  return <AlertDialogPrimitive.Cancel asChild><Button variant="outline" {...props} /></AlertDialogPrimitive.Cancel>
}
function AlertDialogActionButton(props: React.ComponentProps<typeof Button>) {
  return <AlertDialogPrimitive.Action asChild><Button variant="destructive" {...props} /></AlertDialogPrimitive.Action>
}

export { AlertDialog, AlertDialogTrigger, AlertDialogContent, AlertDialogHeader, AlertDialogFooter, AlertDialogTitle, AlertDialogDescription, AlertDialogCancelButton, AlertDialogActionButton }
