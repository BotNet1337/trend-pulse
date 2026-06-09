import z from "zod"

export const changeEmailFormSchema = z.object({
  newEmail: z.string().email("Enter a valid email address"),
  currentPassword: z.string().min(1, "Current password is required"),
})

export type ChangeEmailFormSchema = z.infer<typeof changeEmailFormSchema>
